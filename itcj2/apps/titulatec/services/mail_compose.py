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
  variable (motivos, notas, nombres, lugares). La única pieza con HTML propio
  es la «Información para el alumno» del no adeudo: se sanitiza aquí y se
  marca como `Markup` junto al sanitizador (`_info_biblioteca`), y `|e` la
  respeta; cualquier otra cadena que llegara a ese hueco saldría escapada.
- D11 (spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.11): los dos
  correos de LIBERACIÓN (encuesta liberada, no adeudo liberado) dicen «Ya
  puedes agendar tu cita de cotejo» o «Para agendar te falta: …» con el
  estado VIVO; lo arma UN solo ayudante, `_que_falta`, y las liberaciones las
  decide SOLO `ClearanceGate` (invariante 2): aquí no se compara ningún
  estado de `SurveyReview` ni de `LibraryClearance`. Lo que el egresado debe
  en Caja lo lee el dueño (`LibraryClearanceService.payment_due`), y si
  Biblioteca todavía revisa su caso, también (`LibraryClearanceService.
  reviewable`).
- Orden de los eventos de un grupo: `(created_at, id)`. Las filas de una misma
  transacción comparten `NOW()` y el id desempata.
- Filas que no van juntas (de otro proceso o alumno, de dos grupos, varias
  sueltas, ninguna) → `ValueError`. Es un error del llamador, y adivinar podría
  mandarle a un egresado lo de otro.

CORREOS DE INSCRIPCIÓN (spec 2026-10-05-titulatec-rendimiento-design.md §3.7,
P-D1): los 4 `ENROLLMENT_KINDS` (`enrollment_verified`,
`enrollment_rejected`, `already_enrolled`, `process_cancelled`) tienen su
propio registro, `MailComposer.ENROLLMENT_REGISTRY`, porque NO siguen el
contrato de arriba: usan las MISMAS plantillas de `email_helper` que su envío
en línea (con su `app_url` directo, sin liga al login, y el saludo de esa
plantilla), así que el correo sale idéntico por los dos caminos. Siempre una
fila suelta. `process`/`user` pueden faltar: el rechazo cuelga solo de la
solicitud. La re-validación al enviar (D8): `enrollment_rejected` es
obsoleto si la solicitud ya no está `rejected`; `process_cancelled`, si el
proceso ya no está `cancelled`; los otros dos no tienen forma de quedar
obsoletos. El destinatario y el sello (`rejection_sent_at`) son del
despachador.

EXTENDER: escribir `_compose_<kind>(db, rows, process, user) -> Composed |
Obsolete` en este módulo y darlo de alta en `MailComposer.REGISTRY`. Su
re-validación al enviar (D8) va dentro de esa función: si el correo ya no
aplica, devuelve `Obsolete("motivo legible")`, que va a `last_error`
(String(255)). Así se registraron los recordatorios del barrido diario
(`services/mail_reminders.py`, Tarea 8): `appt_reminder`, `docs_reminder`,
`survey_reminder` y, con el no adeudo de biblioteca, `library_reminder`. Sus
títulos (`asunto_recordatorio_*`) los comparte el aviso in-app que crea el
barrido: un solo texto para los dos canales. Y los tres correos de las
transiciones del no adeudo: `library_ready`, `library_cleared` y
`library_reverted`; y los dos de «Con observaciones» de Biblioteca (spec
2026-10-05 §3.3): `library_observed` y `library_reenabled`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.dates_es import MESES, dia_largo, dia_mes_hora, hora
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
# La liberada por constancia previa (D9): GTV no dictaminó nada en este sistema.
_ASUNTO_ENCUESTA_PREVIA = "Tu encuesta de egresados quedó registrada como liberada"

# D11: lo que falta para agendar, en la voz de «Para agendar te falta: …». Una
# frase por código de `ClearanceGate.BLOCKERS` (conjunto CERRADO; lo cruza
# `test_mail_compose.py`), más la fase 1: el no adeudo se libera desde ella
# (D3) y una constancia previa de encuesta llega desde la inscripción (D9).
_FALTA_FASE_1 = "que Servicios Escolares apruebe tus documentos iniciales"
_FALTA = {
    "survey_missing": "enviar tu encuesta de egresados",
    "survey_in_review": ("que Gestión Tecnológica y Vinculación (GTV) libere tu encuesta "
                         "de egresados (ya la enviaste; está en revisión)"),
    "survey_rejected": ("atender las observaciones de Gestión Tecnológica y Vinculación "
                        "(GTV) a tu encuesta de egresados"),
    "library_pending": "que el Centro de Información revise tu Constancia de no adeudo de biblioteca",
    "library_awaiting_payment": ("pagar en Caja (Recursos Financieros) para liberar tu "
                                 "Constancia de no adeudo de biblioteca"),
    "library_observed": ("atender en la Biblioteca (Centro de Información) las observaciones "
                         "a tu Constancia de no adeudo de biblioteca"),
}
# El de Caja con su total congelado, cuando se conoce.
_FALTA_PAGO = ("pagar {total} en Caja (Recursos Financieros) para liberar tu Constancia de "
               "no adeudo de biblioteca")

# Asuntos del no adeudo de biblioteca (spec 2026-10-01 §4.11), sin prefijo.
_ASUNTO_CAJA = "Ya puedes pasar a Caja por tu Constancia de no adeudo de biblioteca"
_ASUNTO_CAJA_CORREGIDO = "Biblioteca corrigió el monto de tu Constancia de no adeudo de biblioteca"
_ASUNTO_LIBERADO = "Tu Constancia de no adeudo de biblioteca quedó liberada"
_ASUNTO_REVERTIDO = "Se revirtió tu Constancia de no adeudo de biblioteca"
_ASUNTO_OBSERVADO = "Biblioteca registró observaciones en tu Constancia de no adeudo de biblioteca"
_ASUNTO_REHABILITADO = "Biblioteca activó tu trámite: ya puedes continuar con tu Constancia de no adeudo"
_VIAS_LIBERACION = ("payment", "no_charge", "prior")
# El `code` del requisito de cotejo del no adeudo (la «Información para el
# alumno» de `library_ready` sale de él; también en la lista vieja, sin
# `auto_source`).
_CODIGO_REQUISITO_BIBLIOTECA = "library_clearance"


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


def _bloqueos(db: Session, process) -> list[str]:
    """Las liberaciones que le faltan, según el ÚNICO que lo sabe:
    `ClearanceGate` (códigos de `BLOCKERS`, encuesta primero)."""
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate

    return ClearanceGate.blockers(ClearanceGate.status(db, process.id))


def _que_falta(db: Session, process, bloqueos: list[str] | None = None) -> list[str] | None:
    """D11 (spec 2026-10-01 §4.11): qué le falta para agendar su cita de cotejo,
    con el estado VIVO al componer. Lo usan los dos correos de liberación
    (encuesta liberada y no adeudo liberado); la plantilla lo pinta con
    `m.agenda`.

    - `None`: ninguna de las dos frases aplica —el proceso no está `active`
      (en pausa no se agenda), ya aprobó la fase 2 (no hay cita por agendar)
      o su cita vigente OCUPA el cotejo (`SelfBookingService.
      cita_ocupa_el_cotejo`, Ruling R18: agendada, confirmada o en cotejo
      -D17 conserva las agendadas antes del candado, cuyo no adeudo se libera
      después- o atendida mientras la fase 2 no tiene veredicto, D13
      2026-09-30 -mismo predicado y misma lectura de la fase 2 que
      `SelfBookingService.eligibility`, y que ahora también usa `_agenda_ctx`
      del alumno, Ruling R12 de la Tarea 12-). Con la fase 2 `rejected` le
      faltaron papeles y tiene que agendar OTRA: la línea sigue al gate como
      siempre (Ruling R17) —el caso de la transición: un D17 cuyo cotejo se
      rechazó por el no adeudo y que después paga en Caja—. Una `no_show`
      vigente tampoco ocupa el cotejo (agenda una nueva).
    - `[]`: «Ya puedes agendar tu cita de cotejo».
    - Si no, una frase por pendiente: la fase 1 si todavía no la aprueban y,
      en su orden, cada bloqueo de `ClearanceGate` (`bloqueos`, si el llamador
      ya los tiene). El de Caja lleva el total congelado de su fila; leerlo no
      decide nada (lo decidió el gate), igual que en
      `SelfBookingService.eligibility`.
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    if process.status != "active" or process.current_phase > PhaseService.PHASE_COTEJO:
        return None
    cita = AppointmentService.get_for_process(db, process.id)
    if SelfBookingService.cita_ocupa_el_cotejo(db, process, cita):
        return None
    if bloqueos is None:
        bloqueos = _bloqueos(db, process)
    falta = [_FALTA_FASE_1] if process.current_phase < PhaseService.PHASE_COTEJO else []
    for codigo in bloqueos:
        if codigo == "library_awaiting_payment":
            pago = LibraryClearanceService.payment_due(db, process.id)
            total = format_amount(pago["total"]) if pago is not None else ""
            falta.append(_FALTA_PAGO.format(total=total) if total else _FALTA[codigo])
        else:
            falta.append(_FALTA[codigo])
    return falta


def _hay_posterior(db: Session, fila, kind: str) -> bool:
    """¿El proceso tiene una fila `kind` encolada DESPUÉS de `fila` (id mayor),
    en cualquier estado? Cada transición del no adeudo encola la suya: con
    una posterior, `fila` ya no describe cómo quedó."""
    from itcj2.apps.titulatec.models import EmailOutbox

    return (db.query(EmailOutbox.id)
            .filter(EmailOutbox.process_id == fila.process_id,
                    EmailOutbox.kind == kind,
                    EmailOutbox.id > fila.id)
            .first()) is not None


def _hay_entre(db: Session, fila, kind: str, *, despues_de: int) -> bool:
    """¿El proceso tiene una fila `kind` encolada ENTRE la fila de id
    `despues_de` y `fila` (`despues_de < id < fila.id`), en cualquier estado?
    `despues_de=0` = desde el inicio. La gemela acotada de `_hay_posterior`:
    los Rulings R12/R17 la usan para saber si una reversión deshace una
    liberación del ciclo VIGENTE cuyo «quedó liberado» nunca le llegó
    (`despues_de` = W, ver `_compose_library_reverted`)."""
    from itcj2.apps.titulatec.models import EmailOutbox

    return (db.query(EmailOutbox.id)
            .filter(EmailOutbox.process_id == fila.process_id,
                    EmailOutbox.kind == kind,
                    EmailOutbox.id > despues_de,
                    EmailOutbox.id < fila.id)
            .first()) is not None


def _ultima_antes(db: Session, fila, kind: str) -> int | None:
    """El id de la fila `kind` más reciente del proceso encolada ANTES de
    `fila` (id menor), en CUALQUIER estado, o `None`. Para el Ruling R17: la
    reversión anterior, salga o no, cierra el ciclo viejo y es uno de los
    dos extremos posibles de la ventana de `_hay_entre`."""
    from sqlalchemy import func

    from itcj2.apps.titulatec.models import EmailOutbox

    return (db.query(func.max(EmailOutbox.id))
            .filter(EmailOutbox.process_id == fila.process_id,
                    EmailOutbox.kind == kind,
                    EmailOutbox.id < fila.id)
            .scalar())


def _ultimo_enviado(db: Session, fila, kinds: tuple[str, ...]):
    """La fila (`id`, `kind`) más reciente del proceso, entre `kinds`, que
    SALIÓ (`sent`) y se encoló ANTES de `fila` (id menor), o `None` si
    ninguna salió: lo ÚLTIMO que el egresado leyó por correo de esa familia
    de avisos (una fila pendiente, obsoleta, fallida o sin destinatario nunca
    le llegó). Mira hacia atrás, como `_hay_posterior` mira hacia adelante;
    su `id` es uno de los dos extremos posibles de la ventana de `_hay_entre`
    (Rulings R12/R17; el otro, `_ultima_antes`). Supone que las filas `sent`
    del outbox nunca se borran (hoy no existe ninguna tarea de retención).

    Límite conocido (angosto; se documenta, el despachador no cambia): un
    correo que está saliendo todavía no es `sent`. (a) Dos corridas del
    despachador encimadas -nada lo impide; cada unidad toma sus filas con
    `FOR UPDATE SKIP LOCKED` (`mail_dispatch.py`, «TRANSACCIONES Y
    CONCURRENCIA»)-: la corrida A tiene tomado un `library_cleared` mientras
    Graph lo envía y la corrida B compone una reversión encolada entretanto;
    B no lo ve `sent`, así que la reversión sale obsoleta y el «quedó
    liberado» sí llega. (b) Graph lo envió pero falló el commit que lo marca
    `sent` (entrega «al menos una vez»): su reintento sale obsoleto (hay una
    reversión después) y la reversión también, con el mismo desenlace."""
    from itcj2.apps.titulatec.models import EmailOutbox

    return (db.query(EmailOutbox.id, EmailOutbox.kind)
            .filter(EmailOutbox.process_id == fila.process_id,
                    EmailOutbox.kind.in_(kinds),
                    EmailOutbox.status == "sent",
                    EmailOutbox.id < fila.id)
            .order_by(EmailOutbox.id.desc())
            .first())


def _info_biblioteca(db: Session, cohort_id: int):
    """La «Información para el alumno» del requisito de cotejo del no adeudo
    (activo) de la convocatoria, o `None`. Se vuelve a sanitizar al pintar
    (`sanitize_info_html`, como las vistas: un UPDATE a mano tampoco inyecta)
    y se marca como `Markup` AQUÍ, junto al sanitizador: la plantilla la pasa
    por `|e` como todo, que respeta lo ya marcado. Lectura de la columna, no
    siembra."""
    from markupsafe import Markup

    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html

    fila = (db.query(CotejoRequirement.info_html)
            .filter(CotejoRequirement.cohort_id == cohort_id,
                    CotejoRequirement.code == _CODIGO_REQUISITO_BIBLIOTECA,
                    CotejoRequirement.is_active.is_(True))
            .order_by(CotejoRequirement.order_index, CotejoRequirement.id)
            .first())
    limpio = sanitize_info_html(fila[0], max_len=None) if fila is not None and fila[0] else None
    return Markup(limpio) if limpio else None


def _exige_biblioteca(db: Session, process) -> bool:
    """¿Su convocatoria exige el no adeudo para agendar? (`ClearanceGate`,
    invariante 8). Solo entonces los correos del pago dicen que lo necesita
    para agendar."""
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate

    return ClearanceGate.library_required(db, process.cohort_id)


# ---------------------------------------------------------------------------
# Grupos (D7)
# ---------------------------------------------------------------------------
def _compose_docs_group(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#1 + #1b, grupo `docs:{pid}`. De cada documento cuenta su ÚLTIMO dictamen
    del grupo, en el lugar de su primera aparición. Si el grupo trae además el
    avance de la fase 1 (`phase_approved`), el correo da los siguientes pasos
    (encuesta → agendar) y lleva a la cita; si no, lleva a Documentos.

    El asunto de un grupo con avance es «¡aprobados!» SOLO si no queda ningún
    rechazo tras el último dictamen de cada tipo (B4, ronda final): con uno
    —dictamen tardío desde la bandeja, o la fase 1 aprobada a mano con un
    documento rechazado— asunto y encabezado son los de correcciones, y el
    cuerpo menciona el avance."""
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
    con_correcciones = "Revisamos tus documentos: hay correcciones"

    if avance is not None:
        asunto = con_correcciones if hay_correcciones else "¡Tus documentos fueron aprobados!"
        return _correo(user, asunto, "docs_review.html", _CITA,
                       advanced=True, next_name=_texto(avance.get("next_name")),
                       docs=docs, has_rejected=hay_correcciones)
    if not docs:
        return Obsolete("el grupo de documentos no trae dictámenes")
    asunto = con_correcciones if hay_correcciones else "Revisamos tus documentos"
    return _correo(user, asunto, "docs_review.html", _DOCUMENTOS,
                   advanced=False, next_name=None, docs=docs,
                   has_rejected=hay_correcciones)


def _compose_appt_group(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#7, grupo `cita:{pid}`. Se arma con la cita VIGENTE al enviar, no con el
    historial de cada fila (D7): agendar y mover tres veces es UN correo con la
    fecha final.

    - Vigente `scheduled`/`confirmed` → fecha, hora, lugar, qué llevar y
      «confirma tu asistencia» si no la confirmó. «Cambió…» solo si el alumno
      ya conocía su cita y hubo un `rescheduled`; una ráfaga que empieza en la
      creación POR EL ENCARGADO es su primera noticia y dice «Tu cita de
      cotejo: …» (ruling 3, 2026-09-29). La creación por el propio alumno
      (`by == "student"`, auto-agendado) no es primera noticia: él ya conocía
      la fecha, así que si el encargado se la mueve es «Cambió…» (B5, ronda
      final). D11: `AppointmentService.when` decide `sin_horario`; en sin
      horario el asunto lleva el rango en vez de «a las HH:MM» («Tu cita de
      cotejo: 07 de octubre, de 08:00 a 14:00»).
    - Vigente en otro estado (en cotejo, atendida, no se presentó) → obsoleto.
    - Sin vigente (`cancel` le quita la vigencia):
        * el primer evento del grupo es la creación → agendada y cancelada
          dentro de la espera, neto cero → obsoleto;
        * el grupo no trae ningún `cancelled` → la canceló el propio alumno o
          la revocación, vías que no encolan → obsoleto (ruling 2026-09-29);
        * si no → «tu cita fue cancelada» con el motivo de la ÚLTIMA
          cancelación del grupo. D11: resuelve la cita por `appt_id` del
          payload (`db.get`) para saber también si era sin horario; si ya no
          existe, se cae al formato normal con la fecha cruda del payload.
    """
    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    eventos = [_datos(r).get("event") for r in rows]
    vigente = AppointmentService.get_for_process(db, process.id)

    if vigente is not None and vigente.status in _CITA_VIVA:
        cuando = vigente.scheduled_at
        info = AppointmentService.when(vigente)
        primero = _datos(rows[0])
        # Primera noticia = la creación hecha por el ENCARGADO; la que hizo el
        # propio alumno ya la conocía él (B5).
        primera_noticia = (primero.get("event") == "scheduled"
                           and primero.get("by") != "student")
        cambio = not primera_noticia and "rescheduled" in eventos
        # Lectura NO sembradora (ver docstring del módulo).
        requisitos = [{"label": r.label, "hint": _texto(r.hint)}
                      for r in CotejoRequirementService.list(db, process.cohort_id,
                                                             active_only=True)]
        if info["sin_horario"]:
            fecha_asunto = f"{cuando.day:02d} de {MESES[cuando.month]}, {info['hora']}"
        else:
            fecha_asunto = dia_mes_hora(cuando)
        asunto = ("Cambió tu cita de cotejo: " if cambio
                  else "Tu cita de cotejo: ") + fecha_asunto
        return _correo(user, asunto, "appt_changed.html", _CITA,
                       changed=cambio, fecha=info["fecha"], hora=info["hora"],
                       sin_horario=info["sin_horario"], lugar=_texto(vigente.location),
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
    appt_id = _entero(ultima.get("appt_id"))
    appt_cancelada = db.get(ReviewAppointment, appt_id) if appt_id is not None else None
    if appt_cancelada is not None:
        info = AppointmentService.when(appt_cancelada)
        fecha, hora_txt, sin_horario = info["fecha"], info["hora"], info["sin_horario"]
    else:
        cuando = _cuando(ultima.get("scheduled_at"))
        fecha = dia_largo(cuando) if cuando else None
        hora_txt = hora(cuando) if cuando else None
        sin_horario = False
    return _correo(user, "Tu cita de cotejo fue cancelada", "appt_cancelled.html", _CITA,
                   fecha=fecha, hora=hora_txt, sin_horario=sin_horario,
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
    observaciones o revocada). Lleva al tablero en la fase de la cita de cotejo.

    Liberada (spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.11):
    - `origin` del payload llega a la plantilla: `prior` (constancia previa
      del semestre anterior, D9) cambia el texto y el asunto (GTV no
      dictaminó nada aquí); una fila sin él es `submission`, la de siempre.
    - D13: ya no dice «Ya puedes agendar tu cita de cotejo» fijo; lo decide
      D11 (`falta`, `_que_falta`) con el estado VIVO.
    - Re-validada al enviar (D8): si al ENVIAR la encuesta ya no está liberada
      (GTV la revocó dentro de la espera), «liberó tu encuesta» es falso:
      obsoleto, y sale el correo de la revocación.
    Observaciones y revocación: el motivo, y la línea de contacto de D12 la
    pinta la plantilla. La revocación de una constancia previa (`origin=
    'prior'`, Ruling R22) borró la solicitud: el correo le pide contestar la
    encuesta y su botón lleva DIRECTO a ella, no al tablero."""
    from itcj2.apps.titulatec.services.clearance_gate import SURVEY_BLOCKERS
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    datos = _datos(fila)
    resultado, asunto = _GTV[fila.kind]
    origen = "prior" if datos.get("origin") == "prior" else "submission"
    falta = None
    ruta = _tablero(PhaseService.PHASE_COTEJO)
    if resultado == "approved":
        bloqueos = _bloqueos(db, process)
        if any(codigo in SURVEY_BLOCKERS for codigo in bloqueos):
            return Obsolete("la encuesta ya no está liberada")
        falta = _que_falta(db, process, bloqueos)
        if origen == "prior":
            asunto = _ASUNTO_ENCUESTA_PREVIA
    elif resultado == "revoked" and origen == "prior":
        ruta = _ENCUESTA
    return _correo(user, asunto, "survey_result.html", ruta,
                   result=resultado, reason=_texto(datos.get("reason")),
                   origin=origen, falta=falta)


def _compose_appt_no_show(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """#9, «no se presentó», re-validado al enviar (D8): si el encargado lo
    deshizo dentro de la gracia, obsoleto. Si hay OTRA fila de «no se presentó»
    de la MISMA cita más reciente (marcar → deshacer → marcar), sale solo esa
    (ruling 2026-09-29). Y si la cita ya no es la VIGENTE (dentro de la gracia
    se le agendó otra, o se reagendó: el intento nuevo le quita `is_current` y
    la vieja conserva su `no_show`), «Agenda una nueva» sería falso: obsoleto
    (B3, ronda final). D11: `AppointmentService.when` decide `sin_horario`."""
    from itcj2.apps.titulatec.models import EmailOutbox, ReviewAppointment
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

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
    if not appt.is_current:
        return Obsolete("ya hay una cita nueva")
    if appt.status != "no_show":
        return Obsolete("se corrigió la asistencia")
    info = AppointmentService.when(appt)
    return _correo(user, "No registramos tu asistencia a tu cita de cotejo",
                   "appt_no_show.html", _CITA, fecha=info["fecha"], hora=info["hora"],
                   sin_horario=info["sin_horario"])


# ---------------------------------------------------------------------------
# No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-design.md
# §4.11). Individuales; cada uno se re-valida al ENVIAR (D8) y lleva al tablero
# en la fase de la cita de cotejo, como los de GTV.
# ---------------------------------------------------------------------------
def _compose_library_ready(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Pasa a Caja: Biblioteca registró el adeudo, o corrigió el monto.

    - Aplica mientras tenga un pago pendiente en Caja
      (`LibraryClearanceService.payment_due`); si ya pagó, se liberó de otro
      modo, se revirtió a Biblioteca, o su fase 2 YA se aprobó (Ruling R30 #4,
      re-revisión de la ola final: `payment_due` devuelve `None` también ahí
      -`NOT_APPLICABLE`, Ruling R21-, así que TitulaTec deja de perseguir el
      pago por correo con el MISMO `Obsolete` de abajo, sin que este módulo
      pregunte nada aparte; Caja sigue pudiendo cobrarlo si el egresado se
      presenta), obsoleto.
    - Un `library_ready` MÁS NUEVO del proceso lo vuelve obsoleto: los dos
      pintarían los mismos montos vigentes (registrar y corregir dentro de la
      espera del despachador = un solo correo).
    - Pinta los montos VIGENTES de la fila y su nota, no los del payload.
      «Corrigió el monto» solo si el egresado YA recibió (`sent`) un aviso
      anterior de Caja: si no, para él es la primera noticia.
    - Lleva la «Información para el alumno» del requisito, si SE la escribió
      (`_info_biblioteca`), y, donde la convocatoria exige el no adeudo, que
      lo necesita para agendar.
    """
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    pago = LibraryClearanceService.payment_due(db, process.id)
    if pago is None:
        return Obsolete("ya no tiene un pago pendiente en Caja")
    otras = (db.query(EmailOutbox.id, EmailOutbox.status)
             .filter(EmailOutbox.process_id == process.id,
                     EmailOutbox.kind == "library_ready",
                     EmailOutbox.id != fila.id)
             .all())
    if any(otra_id > fila.id for otra_id, _ in otras):
        return Obsolete("hay un aviso más reciente del monto a pagar")
    corrigio = bool(_datos(fila).get("updated")) and any(st == "sent" for _, st in otras)

    return _correo(user, _ASUNTO_CAJA_CORREGIDO if corrigio else _ASUNTO_CAJA,
                   "library_ready.html", _tablero(PhaseService.PHASE_COTEJO),
                   updated=corrigio,
                   debt=format_amount(pago["debt"]), sin_adeudo=not pago["debt"],
                   donation=format_amount(pago["donation"]),
                   con_donacion=bool(pago["donation"]),
                   total=format_amount(pago["total"]),
                   note=_texto(pago["note"]),
                   info_html=_info_biblioteca(db, process.cohort_id),
                   library_required=_exige_biblioteca(db, process))


def _compose_library_cleared(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """El no adeudo quedó liberado: por pago en Caja (con lo que cobró), sin
    cargo (total $0) o por constancia previa (D9, spec folios 2026-10-05: las
    tres dicen que no necesita llevar nada de biblioteca). D11 (`falta`): si
    ya puede agendar o qué le falta.

    Re-validado al enviar (D8): si después se revirtió, «quedó liberado» ya
    es falso, así que obsoleto. Se ve de dos formas: hay un
    `library_reverted` más nuevo del proceso (cualquier convocatoria), o el
    gate ve que el no adeudo volvió a faltar (donde la convocatoria lo exige;
    ahí también si aquel correo no llegó a encolarse). La reversión que lo
    desmiente decide aparte si sale (E10/Ruling R12,
    `_compose_library_reverted`): con ESTE liberado encolado antes que ella y
    sin salir, sale solo si lo último que el egresado recibió por correo del
    no adeudo fue un «quedó liberado». Así, liberar y revertir dentro de la
    misma espera no le manda nada si lo último que ya le había llegado no era
    un liberado.
    """
    from itcj2.apps.titulatec.services.clearance_gate import LIBRARY_BLOCKERS
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    if _hay_posterior(db, fila, "library_reverted"):
        return Obsolete("la Constancia de no adeudo se revirtió después")
    bloqueos = _bloqueos(db, process)
    if any(codigo in LIBRARY_BLOCKERS for codigo in bloqueos):
        return Obsolete("la Constancia de no adeudo ya no está liberada")

    via = _datos(fila).get("via")
    via = via if via in _VIAS_LIBERACION else None
    pagado = None
    if via == "payment":
        # Lo que Caja cobró: el total congelado de la fila (leerlo no decide nada).
        no_adeudo = LibraryClearanceService.get_for_process(db, process.id)
        if no_adeudo is not None:
            pagado = format_amount(no_adeudo.total_amount) or None
    return _correo(user, _ASUNTO_LIBERADO, "library_cleared.html",
                   _tablero(PhaseService.PHASE_COTEJO),
                   via=via, pagado=pagado, falta=_que_falta(db, process, bloqueos))


def _compose_library_reverted(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Se revirtió o deshizo la liberación: el motivo y qué sigue según a dónde
    regresó —a Caja (`awaiting_payment`, con el monto VIGENTE por pagar) o a
    Biblioteca (`pending`)—.

    Re-validado al enviar (D8), obsoleto, en este orden:

    1. Después se volvió a liberar: hay un `library_cleared` más nuevo del
       proceso, y sale ese.
    2. E10 (spec 2026-10-02 §2, m30), afinada por los Rulings R12 y R17 de
       la revisión final (antes R8), en las DOS ramas. Sea S lo ÚLTIMO que
       el egresado recibió por correo del no adeudo: la fila
       `library_cleared` o `library_reverted` más reciente del proceso,
       encolada ANTES que esta y `sent` (`_ultimo_enviado`).
       - S es un «quedó liberado»: sale -es la noticia que lo corrige-.
       - Si no (S es una reversión, o no le llegó ninguno), es obsoleta SOLO
         si hay un `library_cleared` encolado, en cualquier estado, entre
         esta y W (`_hay_entre`). W es el más reciente de S y la reversión
         anterior en cualquier estado (`_ultima_antes`, Ruling R17): una
         reversión, salga o no, cierra el ciclo viejo, así que un liberado
         sin salir de un ciclo ya cerrado no calla la reversión de una
         re-liberación posterior hecha sin correo. Ese `library_cleared`
         del ciclo vigente es liberar y revertir dentro de la misma espera
         del despachador, o Caja equivocándose de renglón, y su «quedó
         liberado» nunca le llegó; «Se revirtió tu no adeudo…» sería ruido
         o, peor, falso.
       - Si no lo hay, sale: un no adeudo legado del backfill (o de la
         promoción D17), una liberación con el correo apagado o una
         re-liberación sin correo no encolaron ningún «quedó liberado» en el
         ciclo vigente, pero el egresado SÍ vio «Liberado» en la app, y este
         correo es el único aviso que le llega por fuera.
       Anclar en lo último ENVIADO, y no en el liberado más reciente saliera
       o no, conserva la reversión legítima de R8: liberado (salió) →
       revertido, re-liberado y revertido en una sola espera ⇒ los dos de en
       medio salen obsoletos (la regla 1 y `_compose_library_cleared`) y
       este sí sale (S es aquel liberado).
    3. Regresó a Caja y ya no tiene pago pendiente (`payment_due`: también
       con la fase 2 ya aprobada, Ruling R30 #4).
    4. Regresó a Biblioteca y Biblioteca ya no revisará su caso
       (`LibraryClearanceService.reviewable` falso: proceso no admitido o
       fase 2 ya aprobada, Ruling R20). Al componer, en la práctica es la
       fase 2 aprobada (m40; p. ej. en una convocatoria sin candado, antes de
       que saliera el correo): el revocado lo descarta antes el despachador
       y un proceso concluido ya la aprobó. «El Centro de Información volverá
       a revisar tu caso» sería falso. Cada rama le pregunta al dueño
       (`payment_due`, `reviewable`); aquí no se compara ningún estado
       (invariante 2).

    Volver a pasar a Caja después NO lo vuelve obsoleto: el motivo de la
    reversión sigue siendo la explicación, y el aviso de Caja sale aparte."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    datos = _datos(fila)
    if _hay_posterior(db, fila, "library_cleared"):
        return Obsolete("la Constancia de no adeudo se volvió a liberar")
    ultimo = _ultimo_enviado(db, fila, ("library_cleared", "library_reverted"))
    if ultimo is None or ultimo.kind != "library_cleared":
        desde = max(ultimo.id if ultimo is not None else 0,
                    _ultima_antes(db, fila, "library_reverted") or 0)
        if _hay_entre(db, fila, "library_cleared", despues_de=desde):
            return Obsolete("no salió el aviso de la liberación que revierte")
    hacia = "awaiting_payment" if datos.get("to_status") == "awaiting_payment" else "pending"
    total = None
    if hacia == "awaiting_payment":
        pago = LibraryClearanceService.payment_due(db, process.id)
        if pago is None:
            return Obsolete("ya no tiene un pago pendiente en Caja")
        total = format_amount(pago["total"]) or None
    elif not LibraryClearanceService.reviewable(db, process.id):
        return Obsolete("Biblioteca ya no revisará su caso: ya pasó su cotejo")
    return _correo(user, _ASUNTO_REVERTIDO, "library_reverted.html",
                   _tablero(PhaseService.PHASE_COTEJO),
                   to_status=hacia, reason=_texto(datos.get("reason")), total=total)


def _compose_library_observed(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Biblioteca registró observaciones en el no adeudo (spec 2026-10-05
    §3.3): el motivo CONGELADO en el payload y «Acude a la Biblioteca».

    Re-validado al enviar (D8), obsoleto si:

    1. Hay un `library_observed` MÁS NUEVO del proceso: actualizó el motivo
       dentro de la espera y sale ese (con el motivo vigente).
    2. Hay un `library_reenabled` más nuevo, o la fila ya no está «Con
       observaciones» (`LibraryClearanceService.observation`, el dueño:
       aquí no se compara ningún estado, invariante 2). Review Focus 4:
       observado y rehabilitado antes del despacho no manda un aviso falso.
    """
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    if _hay_posterior(db, fila, "library_observed"):
        return Obsolete("hay una observación más reciente de Biblioteca")
    if (_hay_posterior(db, fila, "library_reenabled")
            or LibraryClearanceService.observation(db, process.id) is None):
        return Obsolete("Biblioteca ya activó el trámite")
    return _correo(user, _ASUNTO_OBSERVADO, "library_observed.html",
                   _tablero(PhaseService.PHASE_COTEJO),
                   reason=_texto(_datos(fila).get("reason")))


def _compose_library_reenabled(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Biblioteca lo rehabilitó: vuelve a «Por revisar» (spec 2026-10-05
    §3.3). Sale mientras la fila NO esté otra vez «Con observaciones» (en
    `pending` o cualquier estado posterior); obsoleto si lo volvieron a
    observar o si hay un `library_reenabled` más nuevo (sale ese)."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = rows[-1]
    if _hay_posterior(db, fila, "library_reenabled"):
        return Obsolete("hay un aviso más reciente de activación")
    if LibraryClearanceService.observation(db, process.id) is not None:
        return Obsolete("Biblioteca volvió a registrar observaciones")
    return _correo(user, _ASUNTO_REHABILITADO, "library_reenabled.html",
                   _tablero(PhaseService.PHASE_COTEJO))


# ---------------------------------------------------------------------------
# Recordatorios (#8, #10, #11 y el del pago pendiente en Caja, spec 2026-10-01
# §4.11). Los encola el barrido diario (`mail_reminders.MailReminders.run`);
# aquí se re-validan al ENVIAR (D8) y se arman con el estado de ese momento.
# Ninguno aplica a un proceso que ya no está `active` (en pausa o concluido; el
# revocado lo descarta antes el despachador).
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


def asunto_recordatorio_pago(total) -> str:
    """Asunto (y título del aviso in-app) del recordatorio del pago pendiente
    en Caja (spec 2026-10-01 §4.11, D14), con el total congelado (`Decimal`)
    formateado: «Tienes pendiente tu pago de $1,100.00 en Caja». Sin total, la
    frase sale sin la cifra en vez de con un hueco."""
    from itcj2.apps.titulatec.services.library_clearance_service import format_amount

    cifra = format_amount(total)
    return (f"Tienes pendiente tu pago de {cifra} en Caja" if cifra
            else "Tienes pendiente tu pago en Caja")


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
    confirmó. El asunto dice cuándo es de verdad (`asunto_recordatorio_cita`).
    D11: `AppointmentService.when` decide `sin_horario`."""
    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
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
    info = AppointmentService.when(appt)
    requisitos = [{"label": r.label, "hint": _texto(r.hint)}
                  for r in CotejoRequirementService.list(db, process.cohort_id,
                                                         active_only=True)]
    return _correo(user, asunto, "appt_reminder.html", _CITA,
                   titulo=asunto, fecha=info["fecha"], hora=info["hora"],
                   sin_horario=info["sin_horario"], lugar=_texto(appt.location),
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
    en la fase de la cita de cotejo sin haber ENVIADO la encuesta (sin fila en
    `titulatec_survey_reviews`). Deja de aplicar en cuanto la envía, sea cual
    sea su estado después (M-8, revisión final: D1 -2026-09-29, revierte D2
    del 2026-09-15- exige además que Gestión Tecnológica y Vinculación la
    LIBERE antes de poder agendar; este recordatorio solo empuja el ENVÍO,
    nunca la liberación, así que su predicado no cambia con D1). Lleva a la
    encuesta. Donde la convocatoria exige el no adeudo de biblioteca (spec
    2026-10-01 §4.11), avisa que podrá agendar en cuanto GTV la libere Y
    tenga su no adeudo."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    inactivo = _proceso_inactivo(process)
    if inactivo is not None:
        return inactivo
    if process.current_phase != PhaseService.PHASE_COTEJO:
        return Obsolete("ya no está en la fase de la cita de cotejo")
    if SurveyReviewService.get_for_process(db, process.id) is not None:
        return Obsolete("ya envió la encuesta de egresados")
    return _correo(user, ASUNTO_RECORDATORIO_ENCUESTA, "survey_reminder.html", _ENCUESTA,
                   library_required=_exige_biblioteca(db, process))


def _compose_library_reminder(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Recordatorio del pago pendiente en Caja (spec 2026-10-01 §4.11, D14).
    Aplica mientras el proceso siga `active` y su no adeudo tenga un pago
    pendiente (`LibraryClearanceService.payment_due`): deja de salir en cuanto
    se libera, o en cuanto su fase 2 se aprueba (Ruling R30 #4, re-revisión de
    la ola final: `payment_due` devuelve `None` también ahí -`NOT_APPLICABLE`,
    Ruling R21-, así que TitulaTec deja de perseguir el pago por correo con el
    MISMO `Obsolete` de abajo, sin que este módulo pregunte nada aparte; Caja
    sigue pudiendo cobrarlo si el egresado se presenta). `MailReminders._pagos`
    ya no debería encolar este segundo caso (usa el mismo `awaiting_payment_
    clause`), pero esta re-validación es la misma defensa en profundidad que
    el resto de la app. Se arma con el total VIGENTE, que viaja SOLO dentro
    de `titulo` (`asunto_recordatorio_pago`: el asunto y el título del aviso
    in-app; la plantilla no pinta el monto aparte, m31) y, donde la
    convocatoria exige el no adeudo, dice que lo necesita para agendar. Lleva
    al tablero en la fase de la cita de cotejo."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    inactivo = _proceso_inactivo(process)
    if inactivo is not None:
        return inactivo
    pago = LibraryClearanceService.payment_due(db, process.id)
    if pago is None:
        return Obsolete("ya no tiene un pago pendiente en Caja")
    asunto = asunto_recordatorio_pago(pago["total"])
    return _correo(user, asunto, "library_reminder.html", _tablero(PhaseService.PHASE_COTEJO),
                   titulo=asunto, library_required=_exige_biblioteca(db, process))


# ---------------------------------------------------------------------------
# Inscripción: los 4 correos sin secreto (spec 2026-10-05 §3.7, P-D1). Mismas
# plantillas, asuntos y contexto que `TitulaTecEmailHelper.send_*`, con datos
# planos (dicts con los mismos nombres de atributo que la plantilla lee).
# ---------------------------------------------------------------------------
_SIN_PROCESO = "el proceso o su alumno ya no existe"


def _inscripcion(subject: str, template: str, context: dict) -> Composed:
    """`Composed` de un correo de inscripción. Su «liga» es el botón de la
    plantilla (`app_url`), o vacía si no tiene (el rechazo)."""
    return Composed(subject=subject, template=template, context=context,
                    link=context.get("app_url") or "")


def _solicitud(db: Session, fila):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    rid = fila.enrollment_request_id
    return db.get(EnrollmentRequest, rid) if rid is not None else None


def _compose_enrollment_rejected(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Rechazo de la solicitud (`send_enrollment_rejected`): el motivo y quién
    firma, congelados en el payload; nombre y número de control de la
    solicitud. Obsoleto si la solicitud ya no existe o ya no está rechazada, o si
    hay una fila de rechazo MÁS NUEVA para ella: SE deshizo el rechazo
    (`reopen`) y la volvió a rechazar antes del despacho, y esta fila lleva el
    motivo ya deshecho."""
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.services import email_helper

    fila = rows[-1]
    req = _solicitud(db, fila)
    if req is None:
        return Obsolete("la solicitud ya no existe")
    if req.status != "rejected":
        return Obsolete("la solicitud ya no está rechazada")
    mas_nueva = (db.query(EmailOutbox.id)
                 .filter(EmailOutbox.enrollment_request_id == req.id,
                         EmailOutbox.kind == "enrollment_rejected",
                         EmailOutbox.id > fila.id)
                 .first())
    if mas_nueva is not None:
        return Obsolete("hay un rechazo más reciente de la solicitud")
    datos = _datos(fila)
    motivo = datos["reason"] if "reason" in datos else req.review_note
    revisor = _texto(datos.get("revisor"))
    if revisor is None:
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )
        revisor = EnrollmentRequestService.reviewer_label()
    return _inscripcion(
        email_helper.SUBJECT_ENROLLMENT_REJECTED, "enrollment_rejected.html",
        {"req": {"first_name": req.first_name, "last_name": req.last_name,
                 "control_number": req.control_number, "review_note": motivo},
         "revisor": revisor})


def _compose_enrollment_verified(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Aviso con folio al abrir la liga (`send_enrollment_done`). No tiene forma
    de quedar obsoleto: ni la revocación posterior lo calla (es la alarma de
    la dueña de la cuenta)."""
    from itcj2.apps.titulatec.services import email_helper

    if process is None or user is None:
        return Obsolete(_SIN_PROCESO)
    req = _solicitud(db, rows[-1])
    control = req.control_number if req is not None else user.control_number
    return _inscripcion(
        email_helper.SUBJECT_ENROLLMENT_DONE, "enrollment_done.html",
        {"req": {"control_number": control}, "process": {"folio": process.folio},
         "user": {"full_name": user.full_name}, "app_url": email_helper.STUDENT_URL})


def _compose_already_enrolled(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """«Ya tienes un proceso de titulación» (`send_already_enrolled`), con el
    folio y la convocatoria de su proceso vivo. No queda obsoleto."""
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services import email_helper

    if process is None or user is None:
        return Obsolete(_SIN_PROCESO)
    cohort = db.get(Cohort, process.cohort_id)
    return _inscripcion(
        email_helper.SUBJECT_ALREADY_ENROLLED, "already_enrolled.html",
        {"user": {"full_name": user.full_name}, "process": {"folio": process.folio},
         "cohort": {"name": cohort.name} if cohort is not None else None,
         "app_url": email_helper.STUDENT_URL})


def _compose_process_cancelled(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Inscripción revocada (`send_process_cancelled`): sin motivo, folio ni
    número de control. Obsoleto si el proceso ya no está revocado (D8)."""
    from itcj2.apps.titulatec.services import email_helper

    if process is None or user is None:
        return Obsolete(_SIN_PROCESO)
    if process.status != "cancelled":
        return Obsolete("la inscripción ya no está revocada")
    return _inscripcion(
        email_helper.SUBJECT_PROCESS_CANCELLED, "process_cancelled.html",
        {"first_name": user.first_name, "app_url": email_helper.STUDENT_URL})


def _compose_enrollment(db: Session, rows: list, process, user) -> Composed | Obsolete:
    """Entrada de los 4 de inscripción: una sola fila, coherente con el
    proceso y el alumno que se pasan (cualquiera de los dos puede faltar)."""
    if len(rows) != 1:
        raise ValueError(f"MailComposer.compose: {len(rows)} filas de inscripción; "
                         "siempre van sueltas")
    fila = rows[0]
    if fila.group_key:
        raise ValueError("MailComposer.compose: un correo de inscripción no va en grupo")
    if (process is not None and fila.process_id != process.id) or (
            user is not None and fila.user_id != user.id):
        raise ValueError(f"MailComposer.compose: fila de otro proceso o alumno: {[fila.id]}")
    if process is not None and user is not None and user.id != process.student_id:
        raise ValueError("MailComposer.compose: el alumno no es el del proceso")
    return MailComposer.ENROLLMENT_REGISTRY[fila.kind](db, rows, process, user)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
class MailComposer:
    """Qué correo sale de un conjunto de filas del outbox, o por qué ya no."""

    # kind -> fn(db, rows, process, user) -> Composed | Obsolete, para una fila
    # SUELTA: los grupos se reconocen antes, por su `group_key`. `docs_review` y
    # `appt_changed` siempre llegan en su grupo; registrarlos cubre la fila que
    # llegara sin él. Los recordatorios (Tarea 8) y los cuatro del no adeudo de
    # biblioteca (spec 2026-10-01 §4.11) son siempre sueltos.
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
        "library_ready": _compose_library_ready,
        "library_cleared": _compose_library_cleared,
        "library_reverted": _compose_library_reverted,
        "library_reminder": _compose_library_reminder,
        "library_observed": _compose_library_observed,
        "library_reenabled": _compose_library_reenabled,
    }

    # Los 4 correos de inscripción sin secreto (spec 2026-10-05 §3.7): con las
    # plantillas de `email_helper`, fuera del contrato de `REGISTRY` (ver el
    # docstring del módulo). Mismas llaves que `ENROLLMENT_KINDS`.
    ENROLLMENT_REGISTRY: dict[str, Callable[..., Composed | Obsolete]] = {
        "enrollment_verified": _compose_enrollment_verified,
        "enrollment_rejected": _compose_enrollment_rejected,
        "already_enrolled": _compose_already_enrolled,
        "process_cancelled": _compose_process_cancelled,
    }

    @staticmethod
    def compose(db: Session, rows: list[EmailOutbox], process, user) -> Composed | Obsolete:
        """El correo de `rows` (todas del proceso `process`, cuyo alumno es
        `user`): un grupo entero o una fila suelta. Una fila de inscripción
        (`ENROLLMENT_REGISTRY`) admite `process`/`user` en `None`. Contrato
        completo en el docstring del módulo."""
        if not rows:
            raise ValueError("MailComposer.compose: no hay filas que componer")
        if any(r.kind in MailComposer.ENROLLMENT_REGISTRY for r in rows):
            return _compose_enrollment(db, rows, process, user)
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
