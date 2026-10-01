"""Barrido diario de recordatorios por correo al egresado (spec 2026-09-28 §5
#8/#10/#11 y §6 C4; el del pago pendiente en Caja, spec 2026-10-01-titulatec-
biblioteca-caja-design.md §4.11 y D14).

La tarea periódica `titulatec.email_reminders` (diaria, 9:00) llama a
`MailReminders.run`: encola en `titulatec_email_outbox` los recordatorios que
tocan hoy y crea su aviso in-app. Aquí no se envía nada: el despachador
(`titulatec.email_dispatch`, cada 5 minutos) los manda en su corrida siguiente y
los RE-VALIDA al enviar (D8, `mail_compose._compose_*_reminder`); lo que ya no
aplica queda `obsolete`.

QUÉ TOCA (solo procesos `status = 'active'`; cadencia moderada, D6)
- Cita (#8): la VIGENTE (`is_current`), `scheduled`/`confirmed`, cuya FECHA es
  la de hoy + `appt_days_before()`. «Mañana» es la fecha siguiente en `APP_TZ`,
  no «dentro de 24 h»: a las 9:00, la de mañana a las 00:30 sí, la de hoy a
  las 23:30 no (Review Focus 3). Una vez por cita (`appt_reminder:{appt_id}`).
  Se omite la que se agendó o se cambió hace menos de 24 h (`reschedule`
  inserta una fila NUEVA, así que su `created_at` es el del cambio): acaba de
  recibir el correo #7 con esos mismos datos. `appt_days_before() == 0` = sin
  recordatorio de cita.
- Documentos (#10): `current_phase` = la fase `initial_docs`, con documentos
  que faltan o `rejected` (el criterio de `DocumentService.initial_docs_summary`,
  calculado aquí por lote). Ancla = la última actividad: `max(inicio de la fase
  1 —o, sin él, el alta del proceso—, última document_uploaded, última
  document_rejected)`.
- Encuesta (#11): `current_phase` = `PhaseService.PHASE_COTEJO`, sin fila en
  `titulatec_survey_reviews`. Ancla = `started_at` de la fase 2 (sin él, se
  omite).
- Pago pendiente en Caja (spec 2026-10-01 §4.11, D14): su no adeudo de
  biblioteca está `awaiting_payment` (`LibraryClearanceService.
  awaiting_payment_clause`: la comparación vive en el dueño), en CUALQUIER
  fase —Biblioteca lo revisa desde la fase 1, D3—. Ancla = `ready_at`, la
  entrada VIGENTE a Caja (Ruling R10: revertir un pago la vuelve a fijar y la
  cuenta empieza de cero). Al liberarse deja de ser candidato.
- Documentos, encuesta y pago: `due_index(ancla, now, enviados, anterior)`, con
  `enviados` = las filas del outbox de ESA ancla (el prefijo de su
  `dedupe_key`, salieran o no) y `anterior` = el `created_at` de la más nueva de
  ellas. Toca a los `first_days()` del ancla, luego cada `every_days()`, hasta
  `max_reminders()` (0 = nunca); y del segundo en adelante, además, con
  `every_days()` días de CALENDARIO desde el anterior (ruling 19): con un ancla
  vieja (el primer barrido de producción, o el correo que se vuelve a encender)
  la fórmula del ancla ya venció para varios índices, y sin esa espera un
  barrido diario los mandaba en días seguidos. Así sale el 0 el primer día y los
  siguientes cada `every_days()`. El `created_at` de estas filas es el `now` del
  barrido que las encoló (`StudentMail._reminder`): la separación se mide con
  el mismo reloj con el que se compara. Una subida o un rechazo nuevos mueven el
  ancla y la cuenta vuelve a empezar.

IDEMPOTENCIA. Cada recordatorio entra con su `dedupe_key` (`INSERT … ON
CONFLICT DO NOTHING`, en `StudentMail`), y el aviso in-app se crea solo si esa
llamada devolvió `True` (fila nueva): correr el barrido dos veces no duplica ni
correos ni avisos.

TRANSACCIONES Y LECTURAS
- Cada candidato va en su propio SAVEPOINT: su correo y su aviso quedan juntos
  o no queda ninguno. Lo que revienta ahí —o el error de flush que
  `notify_student` se traga, pero que ya deshizo el SAVEPOINT— queda en el log,
  no cuenta y el barrido sigue: la llave deja reintentarlo en la corrida
  siguiente.
- Commit al terminar cada tipo (cita, documentos, encuesta, pago).
- Que celery corte la tarea (`SoftTimeLimitExceeded`) no es la falla de un
  candidato: `_aislado` no se lo traga. El candidato a medias se deshace con
  su SAVEPOINT, `run` commitea lo encolado antes del corte y vuelve a lanzar la
  excepción (mismo patrón del despachador): el barrido termina ahí y lo que
  faltó lo toma la corrida siguiente (las llaves no dejan duplicar).
- Consultas por lote: el número de SELECT no crece con los candidatos (sin N+1
  por proceso).

In-app desde Celery: `notify_student` hace flush y no hay loop para el push de
Socket.IO, así que el aviso aparece al recargar. Es lo esperado.

`TITULATEC_EMAIL_ENABLED = false` → `{"disabled": True}` sin tocar la BD. El
reloj es `now`: por omisión `db_now()`, la hora local naive que escribe
`NOW()` en Postgres (con ella nacen `created_at` y los eventos).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

# Una cita agendada o cambiada hace menos que esto acaba de recibir su correo #7.
_CITA_RECIENTE = timedelta(hours=24)

# Actividad del egresado que mueve el ancla del recordatorio de documentos.
_ACTIVIDAD_DOCS = ("document_uploaded", "document_rejected")

_CUERPO_ENCUESTA = "Sin ella no puedes agendar tu cita de cotejo."

_CUERPO_PAGO = ("Acude a Caja (Recursos Financieros) con tu número de control; "
                "no necesitas cita.")


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _aislado(db: Session, kind: str, process_id: int, paso, *args) -> bool:
    """`paso(*args)` —el correo de UN candidato y, si es nuevo, su aviso— en
    su propio SAVEPOINT. `True` = los dos quedaron en la transacción.

    Si `paso` revienta, el SAVEPOINT se deshace (correo y aviso juntos) y el
    barrido sigue. Si el flush del aviso falló, `notify_student` se traga el
    error pero Postgres ya deshizo el SAVEPOINT, y con él el correo: eso se ve
    en `is_active` y tampoco cuenta. Lo único que lanza es el corte de celery
    (`SoftTimeLimitExceeded`), después de deshacer el SAVEPOINT: no es la falla
    de un candidato y le toca a `run`.
    """
    try:
        with db.begin_nested() as punto:
            hecho = bool(paso(*args))
            if hecho and not punto.is_active:
                logger.warning("[titulatec] Recordatorio %s del proceso %s: su aviso in-app "
                               "falló en la BD y se deshizo junto con el correo; se "
                               "reintenta en la corrida siguiente", kind, process_id)
                hecho = False
        return hecho
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("[titulatec] Recordatorio %s del proceso %s: no se encoló; se "
                         "reintenta en la corrida siguiente", kind, process_id)
        return False


def _llaves(db: Session, kind: str, pids: list) -> dict:
    """`{process_id: [(dedupe_key, created_at)]}` de las filas `kind` de esos
    procesos, en UNA consulta."""
    from itcj2.apps.titulatec.models import EmailOutbox

    out: dict[int, list[tuple[str, datetime]]] = defaultdict(list)
    for pid, llave, creada in (db.query(EmailOutbox.process_id, EmailOutbox.dedupe_key,
                                        EmailOutbox.created_at)
                               .filter(EmailOutbox.kind == kind,
                                       EmailOutbox.process_id.in_(pids),
                                       EmailOutbox.dedupe_key.isnot(None))):
        out[pid].append((llave, creada))
    return out


def _enviados(llaves: dict, kind: str, pid: int,
              ancla: datetime) -> tuple[int, datetime | None]:
    """Recordatorios `kind` ya encolados para ESA ancla —las llaves
    `{kind}:{pid}:{ancla:%Y%m%dT%H%M%S}:{n}` que escribe `StudentMail`— y el
    `created_at` del más nuevo (`None` si no hay). Cuentan todos, salieran o
    no: cada uno ya ocupó su lugar en la cadencia."""
    prefijo = f"{kind}:{pid}:{ancla:%Y%m%dT%H%M%S}:"
    fechas = [creada for llave, creada in llaves.get(pid, ()) if llave.startswith(prefijo)]
    return len(fechas), max(fechas, default=None)


# ---------------------------------------------------------------------------
# Un candidato: el correo y, si la fila es nueva, su aviso in-app
# ---------------------------------------------------------------------------
def _recordar_cita(db: Session, proc, appt, titulo: str) -> bool:
    """#8. El aviso es el mismo de los demás cambios de la cita (fecha · lugar,
    fase 2)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.appointment_reminder(db, proc, appt=appt):
        return False
    AppointmentService._notify_appt(db, proc.id, "APPOINTMENT_REMINDER", titulo, appt)
    return True


def _recordar_documentos(db: Session, proc, ancla: datetime, indice: int, fase: int,
                         faltan: list, corregir: list, now: datetime) -> bool:
    """#10. El aviso nombra lo que falta y lo que hay que corregir."""
    from itcj2.apps.titulatec.services.mail_compose import asunto_recordatorio_documentos
    from itcj2.apps.titulatec.services.notify import notify_student
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.docs_reminder(db, proc, anchor=ancla, index=indice, created_at=now):
        return False
    partes = []
    if faltan:
        partes.append("Por subir: " + ", ".join(faltan) + ".")
    if corregir:
        partes.append("Por corregir: " + ", ".join(corregir) + ".")
    notify_student(db, proc.student_id, type="DOCUMENTS_REMINDER",
                   title=asunto_recordatorio_documentos(bool(faltan)),
                   body=" ".join(partes), process_id=proc.id, phase_number=fase)
    return True


def _recordar_encuesta(db: Session, proc, ancla: datetime, indice: int,
                       now: datetime) -> bool:
    """#11."""
    from itcj2.apps.titulatec.services.mail_compose import ASUNTO_RECORDATORIO_ENCUESTA
    from itcj2.apps.titulatec.services.notify import notify_student
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.survey_reminder(db, proc, anchor=ancla, index=indice,
                                       created_at=now):
        return False
    notify_student(db, proc.student_id, type="SURVEY_REMINDER",
                   title=ASUNTO_RECORDATORIO_ENCUESTA, body=_CUERPO_ENCUESTA,
                   process_id=proc.id, phase_number=PhaseService.PHASE_COTEJO)
    return True


def _recordar_pago(db: Session, proc, ancla: datetime, indice: int, total,
                   now: datetime) -> bool:
    """Pago pendiente en Caja: el aviso dice cuánto (el total congelado de su
    fila) y dónde. Cuelga de la fase 2, como el resto del no adeudo."""
    from itcj2.apps.titulatec.services.mail_compose import asunto_recordatorio_pago
    from itcj2.apps.titulatec.services.notify import notify_student
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.library_reminder(db, proc, anchor=ancla, index=indice,
                                        created_at=now):
        return False
    notify_student(db, proc.student_id, type="LIBRARY_REMINDER",
                   title=asunto_recordatorio_pago(total), body=_CUERPO_PAGO,
                   process_id=proc.id, phase_number=PhaseService.PHASE_COTEJO)
    return True


class MailReminders:
    """Barrido diario de recordatorios. Contrato completo en el docstring del
    módulo."""

    @staticmethod
    def due_index(anchor: datetime, now: datetime, sent: int,
                  last_sent_at: datetime | None = None) -> int | None:
        """Índice del recordatorio que toca encolar para `anchor` (== `sent`, los
        ya encolados para ella) o `None`. Toca si `sent < max_reminders()`,
        `now >= anchor + first_days() + sent * every_days()` (en días) y, para
        `sent >= 1`, además han pasado `every_days()` días desde
        `last_sent_at` —el `created_at` del recordatorio anterior de esa ancla—
        (ruling 19: un ancla vieja no manda varios en días seguidos).

        Esa separación se cuenta en días de CALENDARIO, no en bloques de 24 h:
        el anterior lo encoló el barrido de las 9:00 y el de la semana siguiente
        corre a la misma hora con unos segundos de diferencia (beat no dispara al
        mismo microsegundo); contada en horas, la mitad de las semanas saldría un
        día tarde. `last_sent_at=None` = sin dato del anterior: solo la fórmula
        del ancla."""
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if sent >= MailSettings.max_reminders():
            return None
        cada = MailSettings.every_days()
        vence = anchor + timedelta(days=MailSettings.first_days() + sent * cada)
        if now < vence:
            return None
        if sent >= 1 and last_sent_at is not None \
                and (now.date() - last_sent_at.date()).days < cada:
            return None
        return sent

    @staticmethod
    def run(db: Session, *, now: datetime | None = None) -> dict:
        """Una corrida: `{"disabled": True}` con el correo apagado; si no,
        cuántos recordatorios NUEVOS encoló de cada tipo:
        `{"appt": n, "docs": n, "survey": n, "library": n}`."""
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if not MailSettings.enabled():
            return {"disabled": True}
        now = now or db_now()
        out = {}
        for clave, barrido in (("appt", MailReminders._citas),
                               ("docs", MailReminders._documentos),
                               ("survey", MailReminders._encuestas),
                               ("library", MailReminders._pagos)):
            try:
                out[clave] = barrido(db, now)
            except SoftTimeLimitExceeded:
                # Celery cortó la tarea: lo encolado antes del corte queda firme
                # (el candidato a medias ya se deshizo con su SAVEPOINT) y el
                # corte sigue su camino; lo que faltó lo toma la corrida siguiente.
                logger.warning("[titulatec] Celery cortó el barrido de recordatorios en "
                               "%s: queda lo encolado hasta ahí", clave)
                db.commit()
                raise
            db.commit()          # lo de cada tipo queda firme aunque el siguiente reviente
        return out

    @staticmethod
    def _citas(db: Session, now: datetime) -> int:
        """#8: una consulta con la cita y su proceso."""
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        # `_CITA_VIVA` es la MISMA definición con la que el compositor re-valida
        # al enviar: si el barrido y la re-validación divergieran, se encolaría
        # lo que después sale obsoleto (o al revés).
        from itcj2.apps.titulatec.services.mail_compose import (
            _CITA_VIVA, asunto_recordatorio_cita,
        )
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        dias = MailSettings.appt_days_before()
        if dias <= 0:
            return 0
        # La FECHA objetivo completa: de sus 00:00 a las 00:00 del día siguiente.
        desde = datetime.combine((now + timedelta(days=dias)).date(), time.min)
        filas = (db.query(ReviewAppointment, TitulationProcess)
                 .join(TitulationProcess,
                       TitulationProcess.id == ReviewAppointment.process_id)
                 .filter(TitulationProcess.status == "active",
                         ReviewAppointment.is_current.is_(True),
                         ReviewAppointment.status.in_(sorted(_CITA_VIVA)),
                         ReviewAppointment.scheduled_at >= desde,
                         ReviewAppointment.scheduled_at < desde + timedelta(days=1),
                         ReviewAppointment.created_at <= now - _CITA_RECIENTE)
                 .order_by(ReviewAppointment.id)
                 .all())
        titulo = asunto_recordatorio_cita(dias)
        return sum(_aislado(db, "appt_reminder", proc.id, _recordar_cita,
                            db, proc, appt, titulo)
                   for appt, proc in filas)

    @staticmethod
    def _documentos(db: Session, now: datetime) -> int:
        """#10: procesos con su inicio de fase, documentos, nombres, perfil,
        actividad y llaves -- cinco consultas fijas, más la del perfil
        (`DocumentService.initial_doc_types_by_process`, una sola para todo
        el lote y NINGUNA si nadie trae carrera) cuando hace falta resolver
        el set de posgrado."""
        from sqlalchemy import and_, func

        from itcj2.apps.titulatec.models import (
            Document, DocumentType, ProcessEvent, ProcessPhase, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if MailSettings.max_reminders() <= 0:
            return 0
        fase = PhaseService.phase_number_for_code(db, "initial_docs")
        if fase is None:
            return 0
        filas = (db.query(TitulationProcess, ProcessPhase.started_at)
                 .outerjoin(ProcessPhase,
                            and_(ProcessPhase.process_id == TitulationProcess.id,
                                 ProcessPhase.phase_number == fase))
                 .filter(TitulationProcess.status == "active",
                         TitulationProcess.current_phase == fase)
                 .order_by(TitulationProcess.id)
                 .all())
        if not filas:
            return 0

        # Todos aquí siguen EN la fase de documentos (`current_phase == fase`):
        # R-G (spec 2026-09-30-titulatec-posgrado-design.md §5) no aplica --
        # esa regla es para quien YA la pasó. El set es el DE CADA PROCESO
        # (licenciatura: 3; posgrado: 7), resuelto en LOTE
        # (`initial_doc_types_by_process`); la consulta de estados usa la
        # UNIÓN de todos los sets para no repetir un SELECT por perfil
        # distinto, y cada proceso decide "falta"/"corregir" contra el SUYO.
        # El criterio es el de `initial_docs_summary`: sin fila = falta;
        # `rejected` = por corregir. Nombres del catálogo (sin `is_active`,
        # como allá), o el código si no hay fila.
        procesos = [p for p, _ in filas]
        codes_by_process = DocumentService.initial_doc_types_by_process(db, procesos)
        union_codigos = sorted({c for codigos in codes_by_process.values() for c in codigos})
        estados: dict[int, dict[str, str]] = defaultdict(dict)
        for pid, codigo, estado in (db.query(Document.process_id, Document.type_code,
                                             Document.review_status)
                                    .filter(Document.process_id.in_([p.id for p in procesos]),
                                            Document.type_code.in_(union_codigos))):
            estados[pid][codigo] = estado
        nombres = dict(db.query(DocumentType.code, DocumentType.name)
                       .filter(DocumentType.code.in_(union_codigos)).all())

        pendientes = {}
        for proc, inicio in filas:
            codigos = codes_by_process.get(proc.id, DocumentService.BASE_INITIAL_DOCS)
            docs = estados.get(proc.id, {})
            faltan = [nombres.get(c, c) for c in codigos if c not in docs]
            corregir = [nombres.get(c, c) for c in codigos if docs.get(c) == "rejected"]
            if faltan or corregir:
                pendientes[proc.id] = (proc, inicio or proc.created_at, faltan, corregir)
        if not pendientes:
            return 0

        pids = list(pendientes)
        actividad = dict(db.query(ProcessEvent.process_id, func.max(ProcessEvent.created_at))
                         .filter(ProcessEvent.process_id.in_(pids),
                                 ProcessEvent.event_type.in_(_ACTIVIDAD_DOCS))
                         .group_by(ProcessEvent.process_id)
                         .all())
        llaves = _llaves(db, "docs_reminder", pids)

        n = 0
        for pid, (proc, base, faltan, corregir) in pendientes.items():
            ultima = actividad.get(pid)
            ancla = base if ultima is None else max(base, ultima)
            indice = MailReminders.due_index(
                ancla, now, *_enviados(llaves, "docs_reminder", pid, ancla))
            if indice is not None:
                n += _aislado(db, "docs_reminder", pid, _recordar_documentos,
                              db, proc, ancla, indice, fase, faltan, corregir, now)
        return n

    @staticmethod
    def _encuestas(db: Session, now: datetime) -> int:
        """#11: procesos con el inicio de su fase 2 y llaves, dos consultas."""
        from sqlalchemy import and_, exists

        from itcj2.apps.titulatec.models import ProcessPhase, SurveyReview, TitulationProcess
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if MailSettings.max_reminders() <= 0:
            return 0
        fase = PhaseService.PHASE_COTEJO
        sin_encuesta = ~exists().where(SurveyReview.process_id == TitulationProcess.id)
        filas = (db.query(TitulationProcess, ProcessPhase.started_at)
                 .join(ProcessPhase,
                       and_(ProcessPhase.process_id == TitulationProcess.id,
                            ProcessPhase.phase_number == fase))
                 .filter(TitulationProcess.status == "active",
                         TitulationProcess.current_phase == fase,
                         ProcessPhase.started_at.isnot(None),
                         sin_encuesta)
                 .order_by(TitulationProcess.id)
                 .all())
        if not filas:
            return 0

        llaves = _llaves(db, "survey_reminder", [p.id for p, _ in filas])
        n = 0
        for proc, ancla in filas:
            indice = MailReminders.due_index(
                ancla, now, *_enviados(llaves, "survey_reminder", proc.id, ancla))
            if indice is not None:
                n += _aislado(db, "survey_reminder", proc.id, _recordar_encuesta,
                              db, proc, ancla, indice, now)
        return n

    @staticmethod
    def _pagos(db: Session, now: datetime) -> int:
        """Pago pendiente en Caja (spec 2026-10-01 §4.11, D14): procesos
        `active` de cualquier fase con su no adeudo `awaiting_payment`, su
        entrada a Caja (`ready_at`, el ancla) y su total congelado (para el
        aviso), y sus llaves: dos consultas. Una fila sin `ready_at` no tiene
        ancla y se omite (`_mark_ready` siempre lo fija)."""
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if MailSettings.max_reminders() <= 0:
            return 0
        filas = (db.query(TitulationProcess, LibraryClearance.ready_at,
                          LibraryClearance.total_amount)
                 .join(LibraryClearance, LibraryClearance.process_id == TitulationProcess.id)
                 .filter(TitulationProcess.status == "active",
                         LibraryClearanceService.awaiting_payment_clause(),
                         LibraryClearance.ready_at.isnot(None))
                 .order_by(TitulationProcess.id)
                 .all())
        if not filas:
            return 0

        llaves = _llaves(db, "library_reminder", [p.id for p, _, _ in filas])
        n = 0
        for proc, ancla, total in filas:
            indice = MailReminders.due_index(
                ancla, now, *_enviados(llaves, "library_reminder", proc.id, ancla))
            if indice is not None:
                n += _aislado(db, "library_reminder", proc.id, _recordar_pago,
                              db, proc, ancla, indice, total, now)
        return n
