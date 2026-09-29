"""Composición de los correos del proceso al egresado (spec 2026-09-28 §5; §6 C3.6).

Dado un conjunto de filas YA encoladas en `titulatec_email_outbox` (todas del
mismo proceso: un grupo `docs:`/`cita:` entero, o una fila suelta), decide QUÉ
correo sale —asunto, plantilla, contexto y liga— o si ya no aplica
(`Obsolete`). Aquí no se envía ni se escribe nada: el despachador
(`titulatec.email_dispatch`) renderiza `Composed.template` con
`Composed.context`, lo manda y marca las filas.

CONTRATO DE `MailComposer.compose(db, rows, process, user)`:

- Grupo `docs:` → `_compose_docs_group`; grupo `cita:` → `_compose_appt_group`;
  si no, una fila suelta → `REGISTRY[kind]`. Un `kind` sin composición →
  `Obsolete` + error en el log: una fila que se reintentara sin fin atascaría
  el lote del despachador.
- Solo LECTURA: ni commit, ni flush, ni siembra. Por eso los requisitos de la
  cita salen de `CotejoRequirementService.list` y NUNCA de
  `RequirementService.list_with_status` ni `CotejoRequirementService.list_or_seed`,
  que siembran Y commitean.
- `context` son datos PLANOS (texto, booleanos, listas de dicts): ningún objeto
  ORM, que en producción (`expire_on_commit=True`) se recargaría a media
  plantilla. Siempre trae `first_name` y `link`; `link` es
  `StudentMail.link(ruta)` y es el mismo valor que `Composed.link`.
- `Composed.template` es el archivo bajo `titulatec/email/`: lo que recibe
  `email_helper._render`. Todas las plantillas escapan con `|e` cada texto
  variable (motivos, notas, nombres, lugares).
- Orden de los eventos de un grupo: `(created_at, id)`. Las filas de una misma
  transacción comparten `NOW()` y el id desempata.
- Filas que no van juntas (de otro proceso o alumno, de dos grupos, varias
  sueltas, ninguna) → `ValueError`. Es un error del llamador, y adivinar podría
  mandarle a un egresado lo de otro.

EXTENDER: escribir `_compose_<kind>(db, rows, process, user) -> Composed |
Obsolete` en este módulo y darlo de alta en `MailComposer.REGISTRY`. Su
re-validación al enviar (D8) va dentro de esa función: si el correo ya no
aplica, devuelve `Obsolete("motivo legible")`, que va a `last_error`
(String(255)). Así se registraron los tres recordatorios del barrido diario
(`services/mail_reminders.py`, Tarea 8): `appt_reminder`, `docs_reminder` y
`survey_reminder`. Sus títulos (`asunto_recordatorio_*`) los comparte el aviso
in-app que crea el barrido: un solo texto para los dos canales.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.dates_es import dia_largo, dia_mes_hora, hora
from itcj2.core.utils.timezone import db_now

if TYPE_CHECKING:  # solo para las anotaciones: los modelos se importan dentro de cada función
    from itcj2.apps.titulatec.models.email_outbox import EmailOutbox

logger = logging.getLogger(__name__)

# Prefijo EXACTO de todo asunto (Global Constraints del plan).
_PREFIJO = "[TitulaTec ITCJ] "

# Pantallas del egresado a las que lleva cada correo (spec §5). Pasan por
# `StudentMail.link`, que exige que `safe_next` las acepte tal cual. La
# encuesta de egresados es la única fuera de `/titulatec/student/`: vive en
# `pages/public.py` (con sesión, precarga sus datos).
_DOCUMENTOS = "/titulatec/student/documents"
_CITA = "/titulatec/student/cita"
_TABLERO = "/titulatec/student/dashboard"
_ENCUESTA = "/titulatec/encuesta-egresados"

# Cita VIGENTE de la que se avisa fecha y lugar: la que todavía va a ocurrir.
_CITA_VIVA = frozenset({"scheduled", "confirmed"})

# Cómo se lee en `last_error` («Ya no aplicaba») una vigente que ya pasó de eso.
_CITA_YA = {
    "in_progress": "en cotejo",
    "attended": "atendida",
    "no_show": "marcada como «no se presentó»",
}

# Dictamen de GTV: kind -> (resultado para la plantilla, asunto sin prefijo).
_GTV = {
    "survey_approved": ("approved", "GTV liberó tu encuesta de egresados"),
    "survey_rejected": ("rejected", "GTV dejó observaciones en tu encuesta de egresados"),
    "survey_revoked": ("revoked", "Se revocó la liberación de tu encuesta de egresados"),
}


@dataclass(frozen=True)
class Composed:
    """Un correo listo para `email_helper`: `template` es el archivo bajo
    `titulatec/email/`, `context` son datos planos y `link` es la misma liga
    que `context["link"]`."""
    subject: str
    template: str
    context: dict
    link: str


@dataclass(frozen=True)
class Obsolete:
    """Ya no aplica y no sale. `reason` es legible: va a `last_error`."""
    reason: str


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _orden(row) -> tuple:
    """Orden de los eventos de un grupo: `created_at` y, en empate, id."""
    return (row.created_at or datetime.min, row.id or 0)


def _datos(row) -> dict:
    """El payload de la fila. Uno que no sea dict se lee como vacío en vez de
    tumbar la composición."""
    return row.payload if isinstance(row.payload, dict) else {}


def _texto(valor) -> str | None:
    """Texto del payload sin espacios de sobra; vacío o ausente = `None`, para
    que la plantilla lo omita en vez de pintar un hueco."""
    if valor is None:
        return None
    return str(valor).strip() or None


def _entero(valor) -> int | None:
    """Número del payload (fase, id de cita), o `None` si no es un entero."""
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _cuando(valor) -> datetime | None:
    """Fecha ISO del payload a `datetime`; inválida o ausente = `None`."""
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _nombre_fase(nombre, numero: int | None) -> str:
    """'Fase NN · Nombre' tal como viene del payload, con respaldo si faltara."""
    return _texto(nombre) or (f"Fase {numero:02d}" if numero is not None else "fase")


def _tablero(fase: int | None) -> str:
    """Tablero del egresado con el acordeón abierto en `fase` (deep-link `?fase=N`)."""
    return f"{_TABLERO}?fase={fase}" if fase is not None else _TABLERO


def _correo(user, asunto: str, plantilla: str, ruta: str, **datos) -> Composed:
    """Arma el `Composed`: prefijo del asunto, liga al login con `next` y el
    contexto común (`first_name`, `link`) más los datos de la plantilla."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    link = StudentMail.link(ruta)
    return Composed(subject=_PREFIJO + asunto, template=plantilla,
                    context={"first_name": user.first_name, "link": link, **datos},
                    link=link)


# ---------------------------------------------------------------------------
# Grupos (D7)
# ---------------------------------------------------------------------------
def _compose_docs_group(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#1 + #1b, grupo `docs:{pid}`. De cada documento cuenta su ÚLTIMO dictamen
    del grupo, en el lugar de su primera aparición. Si el grupo trae además el
    avance de la fase 1 (`phase_approved`), el correo es «¡aprobados!» con los
    siguientes pasos (encuesta → agendar) y lleva a la cita; si no, lleva a
    Documentos."""
    ultimos: dict[str, dict] = {}
    avance = None
    for row in rows:                                   # ya en orden (created_at, id)
        datos = _datos(row)
        if row.kind == "docs_review":
            clave = (_texto(datos.get("type_code")) or _texto(datos.get("name"))
                     or f"#{row.id}")
            ultimos[clave] = datos      # reasignar conserva el lugar de la primera clave
        elif row.kind == "phase_approved":
            avance = datos

    docs = []
    for datos in ultimos.values():
        aprobado = datos.get("status") == "approved"
        docs.append({
            "name": _texto(datos.get("name")) or _texto(datos.get("type_code")) or "Documento",
            "approved": aprobado,
            # El motivo tal como estaba al dictaminar; solo de lo que hay que corregir.
            "note": None if aprobado else _texto(datos.get("note")),
        })
    hay_correcciones = any(not d["approved"] for d in docs)

    if avance is not None:
        return _correo(user, "¡Tus documentos fueron aprobados!", "docs_review.html", _CITA,
                       advanced=True, next_name=_texto(avance.get("next_name")),
                       docs=docs, has_rejected=hay_correcciones)
    if not docs:
        return Obsolete("el grupo de documentos no trae dictámenes")
    asunto = ("Revisamos tus documentos: hay correcciones" if hay_correcciones
              else "Revisamos tus documentos")
    return _correo(user, asunto, "docs_review.html", _DOCUMENTOS,
                   advanced=False, next_name=None, docs=docs,
                   has_rejected=hay_correcciones)


def _compose_appt_group(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#7, grupo `cita:{pid}`. Se arma con la cita VIGENTE al enviar, no con el
    historial de cada fila (D7): agendar y mover tres veces es UN correo con la
    fecha final.

    - Vigente `scheduled`/`confirmed` → fecha, hora, lugar, qué llevar y
      «confirma tu asistencia» si no la confirmó. «Cambió…» solo si el alumno
      ya conocía su cita (el primer evento del grupo NO es la creación) y hubo
      un `rescheduled`; una ráfaga que empieza en la creación es su primera
      noticia y dice «Tu cita de cotejo: …» (ruling 3, 2026-09-29).
    - Vigente en otro estado (en cotejo, atendida, no se presentó) → obsoleto.
    - Sin vigente (`cancel` le quita la vigencia):
        * el primer evento del grupo es la creación → agendada y cancelada
          dentro de la espera, neto cero → obsoleto;
        * el grupo no trae ningún `cancelled` → la canceló el propio alumno o
          la revocación, vías que no encolan → obsoleto (ruling 2026-09-29);
        * si no → «tu cita fue cancelada» con el motivo de la ÚLTIMA
          cancelación del grupo.
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    eventos = [_datos(r).get("event") for r in rows]
    vigente = AppointmentService.get_for_process(db, process.id)

    if vigente is not None and vigente.status in _CITA_VIVA:
        cuando = vigente.scheduled_at
        cambio = eventos[0] != "scheduled" and "rescheduled" in eventos
        # Lectura NO sembradora (ver docstring del módulo).
        requisitos = [{"label": r.label, "hint": _texto(r.hint)}
                      for r in CotejoRequirementService.list(db, process.cohort_id,
                                                             active_only=True)]
        asunto = ("Cambió tu cita de cotejo: " if cambio
                  else "Tu cita de cotejo: ") + dia_mes_hora(cuando)
        return _correo(user, asunto, "appt_changed.html", _CITA,
                       changed=cambio, fecha=dia_largo(cuando), hora=hora(cuando),
                       lugar=_texto(vigente.location),
                       confirmar=vigente.confirmed_at is None, requisitos=requisitos)

    if vigente is not None:
        return Obsolete("la cita vigente ya está "
                        + _CITA_YA.get(vigente.status, str(vigente.status)))

    if eventos and eventos[0] == "scheduled":
        return Obsolete("agendada y cancelada dentro de la espera")
    cancelaciones = [_datos(r) for r in rows if _datos(r).get("event") == "cancelled"]
    if not cancelaciones:
        return Obsolete("la cita se canceló por una vía sin correo")
    ultima = cancelaciones[-1]
    cuando = _cuando(ultima.get("scheduled_at"))
    return _correo(user, "Tu cita de cotejo fue cancelada", "appt_cancelled.html", _CITA,
                   fecha=dia_largo(cuando) if cuando else None,
                   hora=hora(cuando) if cuando else None,
                   reason=_texto(ultima.get("reason")))


# ---------------------------------------------------------------------------
# Correos sueltos
# ---------------------------------------------------------------------------
def _compose_phase_approved(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#2, fase aprobada (cualquiera salvo `initial_docs`, que va en el grupo
    `docs:`): «¡Proceso completado!» si no hay siguiente; «Concluiste tu trámite
    con Servicios Escolares» si la siguiente ya la opera T-soft (`handoff`); si
    no, «Avanzaste a {siguiente}». Lleva al tablero en la fase que sigue."""
    datos = _datos(rows[-1])
    fase = _entero(datos.get("phase_number"))
    siguiente = _entero(datos.get("next_phase"))
    siguiente_nombre = None
    if datos.get("completed") or siguiente is None:
        variante, asunto = "completed", "¡Proceso completado!"
    elif datos.get("handoff"):
        variante, asunto = "handoff", "Concluiste tu trámite con Servicios Escolares"
    else:
        siguiente_nombre = _nombre_fase(datos.get("next_name"), siguiente)
        variante, asunto = "advanced", f"Avanzaste a {siguiente_nombre}"
    return _correo(user, asunto, "phase_approved.html",
                   _tablero(siguiente if siguiente is not None else fase),
                   variant=variante, phase_name=_nombre_fase(datos.get("phase_name"), fase),
                   next_name=siguiente_nombre)


def _compose_phase_rejected(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#3, fase rechazada: el motivo tal como quedó y qué hacer."""
    datos = _datos(rows[-1])
    fase = _entero(datos.get("phase_number"))
    nombre = _nombre_fase(datos.get("phase_name"), fase)
    return _correo(user, f"Una fase necesita correcciones: {nombre}", "phase_rejected.html",
                   _tablero(fase), phase_name=nombre, reason=_texto(datos.get("reason")))


def _compose_survey(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#4-#6, dictamen de GTV sobre la encuesta de egresados (liberada, con
    observaciones o revocada). Lleva al tablero en la fase de la cita de cotejo."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    resultado, asunto = _GTV[fila.kind]
    return _correo(user, asunto, "survey_result.html", _tablero(PhaseService.PHASE_COTEJO),
                   result=resultado, reason=_texto(_datos(fila).get("reason")))


def _compose_appt_no_show(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#9, «no se presentó», re-validado al enviar (D8): si el encargado lo
    deshizo dentro de la gracia, obsoleto. Si hay OTRA fila de «no se presentó»
    de la MISMA cita más reciente (marcar → deshacer → marcar), sale solo esa
    (ruling 2026-09-29)."""
    from itcj2.apps.titulatec.models import EmailOutbox, ReviewAppointment

    fila = rows[-1]
    appt_id = _entero(_datos(fila).get("appt_id"))
    posteriores = (db.query(EmailOutbox)
                   .filter(EmailOutbox.process_id == process.id,
                           EmailOutbox.kind == "appt_no_show",
                           EmailOutbox.id > fila.id)
                   .all())
    if any(_entero(_datos(otra).get("appt_id")) == appt_id for otra in posteriores):
        return Obsolete("hay un aviso más reciente de la misma cita")

    appt = db.get(ReviewAppointment, appt_id) if appt_id is not None else None
    if appt is None or appt.process_id != process.id:
        return Obsolete("la cita ya no existe")
    if appt.status != "no_show":
        return Obsolete("se corrigió la asistencia")
    cuando = appt.scheduled_at
    return _correo(user, "No registramos tu asistencia a tu cita de cotejo",
                   "appt_no_show.html", _CITA, fecha=dia_largo(cuando), hora=hora(cuando))


# ---------------------------------------------------------------------------
# Recordatorios (#8, #10, #11). Los encola el barrido diario
# (`mail_reminders.MailReminders.run`); aquí se re-validan al ENVIAR (D8) y se
# arman con el estado de ese momento. Ninguno aplica a un proceso que ya no
# está `active` (en pausa o concluido; el revocado lo descarta antes el
# despachador).
# ---------------------------------------------------------------------------
ASUNTO_RECORDATORIO_ENCUESTA = "Llena tu encuesta de egresados"


def asunto_recordatorio_cita(dias: int) -> str:
    """Asunto (y título del aviso in-app) del recordatorio de cita según los
    días de CALENDARIO que faltan. Con el valor por omisión
    (`TITULATEC_APPT_REMINDER_DAYS_BEFORE = 1`) es «Mañana es tu cita de
    cotejo»; el setting admite hasta 7 días, y un correo reintentado puede
    salir ya el día de la cita: ahí «mañana» sería falso."""
    if dias <= 0:
        return "Hoy es tu cita de cotejo"
    if dias == 1:
        return "Mañana es tu cita de cotejo"
    return f"Tu cita de cotejo es en {dias} días"


def asunto_recordatorio_documentos(por_subir: bool) -> str:
    """Asunto (y título del aviso in-app) del recordatorio de documentos: «por
    subir» si falta alguno; «por corregir» si solo quedan rechazados."""
    return ("Te faltan documentos por subir" if por_subir
            else "Te faltan documentos por corregir")


def _proceso_inactivo(process) -> Obsolete | None:
    """Los recordatorios son solo de procesos `active` (spec C4)."""
    if process.status != "active":
        return Obsolete("el proceso ya no está activo")
    return None


def _compose_appt_reminder(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#8, recordatorio de la cita. Aplica si la cita del payload sigue siendo
    la VIGENTE, activa (`scheduled`/`confirmed`), con la misma fecha y todavía
    en el futuro. Se arma con la cita vigente como #7: fecha, hora, lugar, qué
    llevar (lectura NO sembradora) y «confirma tu asistencia» si no la
    confirmó. El asunto dice cuándo es de verdad (`asunto_recordatorio_cita`)."""
    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    inactivo = _proceso_inactivo(process)
    if inactivo is not None:
        return inactivo
    datos = _datos(rows[-1])
    appt_id = _entero(datos.get("appt_id"))
    appt = db.get(ReviewAppointment, appt_id) if appt_id is not None else None
    if appt is None or appt.process_id != process.id:
        return Obsolete("la cita ya no existe")
    if not appt.is_current:
        return Obsolete("la cita ya no es la vigente")
    if appt.status not in _CITA_VIVA:
        return Obsolete("la cita ya está " + _CITA_YA.get(appt.status, str(appt.status)))
    cuando = appt.scheduled_at
    if _cuando(datos.get("scheduled_at")) != cuando:
        return Obsolete("la cita cambió de fecha")
    ahora = db_now()
    if cuando <= ahora:
        return Obsolete("la cita ya pasó")

    asunto = asunto_recordatorio_cita((cuando.date() - ahora.date()).days)
    requisitos = [{"label": r.label, "hint": _texto(r.hint)}
                  for r in CotejoRequirementService.list(db, process.cohort_id,
                                                         active_only=True)]
    return _correo(user, asunto, "appt_reminder.html", _CITA,
                   titulo=asunto, fecha=dia_largo(cuando, hoy=ahora.date()),
                   hora=hora(cuando), lugar=_texto(appt.location),
                   confirmar=appt.confirmed_at is None, requisitos=requisitos)


def _compose_docs_reminder(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#10, recordatorio de documentos. Aplica si el proceso sigue en la fase
    `initial_docs` con documentos que faltan o que hay que corregir. Los
    nombres salen del estado ACTUAL (`DocumentService.initial_docs_summary`),
    no del payload: lo que subió después de encolarse ya no se le pide."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    inactivo = _proceso_inactivo(process)
    if inactivo is not None:
        return inactivo
    inicial = PhaseService.phase_number_for_code(db, "initial_docs")
    if inicial is None or process.current_phase != inicial:
        return Obsolete("ya no está en la fase de documentos")
    items = DocumentService.initial_docs_summary(db, process.id)["items"]
    faltantes = [d["name"] for d in items if d["status"] == "missing"]
    por_corregir = [d["name"] for d in items if d["status"] == "rejected"]
    if not (faltantes or por_corregir):
        return Obsolete("ya no le faltan documentos ni tiene por corregir")
    return _correo(user, asunto_recordatorio_documentos(bool(faltantes)),
                   "docs_reminder.html", _DOCUMENTOS,
                   faltantes=faltantes, por_corregir=por_corregir)


def _compose_survey_reminder(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#11, recordatorio de la encuesta de egresados. Aplica si el proceso sigue
    en la fase de la cita de cotejo sin haberla enviado (sin fila en
    `titulatec_survey_reviews`: con ella ya puede agendar, D2). Lleva a la
    encuesta."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    inactivo = _proceso_inactivo(process)
    if inactivo is not None:
        return inactivo
    if process.current_phase != PhaseService.PHASE_COTEJO:
        return Obsolete("ya no está en la fase de la cita de cotejo")
    if SurveyReviewService.get_for_process(db, process.id) is not None:
        return Obsolete("ya envió la encuesta de egresados")
    return _correo(user, ASUNTO_RECORDATORIO_ENCUESTA, "survey_reminder.html", _ENCUESTA)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
class MailComposer:
    """Qué correo sale de un conjunto de filas del outbox, o por qué ya no."""

    # kind -> fn(db, rows, process, user) -> Composed | Obsolete, para una fila
    # SUELTA: los grupos se reconocen antes, por su `group_key`. `docs_review` y
    # `appt_changed` siempre llegan en su grupo; registrarlos cubre la fila que
    # llegara sin él. Los tres recordatorios (Tarea 8) son siempre sueltos.
    REGISTRY: dict[str, Callable[..., Composed | Obsolete]] = {
        "docs_review": _compose_docs_group,
        "phase_approved": _compose_phase_approved,
        "phase_rejected": _compose_phase_rejected,
        "survey_approved": _compose_survey,
        "survey_rejected": _compose_survey,
        "survey_revoked": _compose_survey,
        "appt_changed": _compose_appt_group,
        "appt_no_show": _compose_appt_no_show,
        "appt_reminder": _compose_appt_reminder,
        "docs_reminder": _compose_docs_reminder,
        "survey_reminder": _compose_survey_reminder,
    }

    @staticmethod
    def compose(db: Session, rows: list[EmailOutbox], process, user) -> Composed | Obsolete:
        """El correo de `rows` (todas del proceso `process`, cuyo alumno es
        `user`): un grupo entero o una fila suelta. Contrato completo en el
        docstring del módulo."""
        if not rows:
            raise ValueError("MailComposer.compose: no hay filas que componer")
        if process is None or user is None or user.id != process.student_id:
            raise ValueError("MailComposer.compose: el alumno no es el del proceso")
        ajenas = [r.id for r in rows
                  if r.process_id != process.id or r.user_id != user.id]
        if ajenas:
            raise ValueError(f"MailComposer.compose: filas de otro proceso o alumno: {ajenas}")
        grupos = {r.group_key for r in rows}
        if len(grupos) > 1:
            raise ValueError("MailComposer.compose: filas de grupos distintos: "
                             f"{sorted(str(g) for g in grupos)}")

        grupo = grupos.pop() or ""
        filas = sorted(rows, key=_orden)
        if grupo.startswith("docs:"):
            return _compose_docs_group(db, filas, process, user)
        if grupo.startswith("cita:"):
            return _compose_appt_group(db, filas, process, user)
        if len(filas) > 1:
            raise ValueError(f"MailComposer.compose: {len(filas)} filas sin un grupo "
                             "que las junte")

        kind = filas[0].kind
        fn = MailComposer.REGISTRY.get(kind)
        if fn is None:
            logger.error("[titulatec] Correo %s sin composición (fila %s): queda obsoleto",
                         kind, filas[0].id)
            return Obsolete(f"sin composición para el tipo {kind}")
        return fn(db, filas, process, user)
