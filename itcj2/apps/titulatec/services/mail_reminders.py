"""Barrido diario de recordatorios por correo al egresado (spec 2026-09-28 §5
#8/#10/#11 y §6 C4).

La tarea periódica `titulatec.email_reminders` (diaria, 9:00) llama a
`MailReminders.run`: encola en `titulatec_email_outbox` los recordatorios que
tocan hoy y crea su aviso in-app. Aquí no se envía nada: el despachador
(`titulatec.email_dispatch`) los manda en el minuto siguiente y los RE-VALIDA al
enviar (D8, `mail_compose._compose_*_reminder`); lo que ya no aplica queda
`obsolete`.

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
- Documentos y encuesta: `due_index(ancla, now, enviados)`, con `enviados` = las
  filas del outbox de ESA ancla (el prefijo de su `dedupe_key`, salieran o no).
  Toca a los `first_days()` del ancla, luego cada `every_days()`, hasta
  `max_reminders()` (0 = nunca). Una subida o un rechazo nuevos mueven el ancla
  y la cuenta vuelve a empezar.

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
- Commit al terminar cada tipo (cita, documentos, encuesta).
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

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

# Una cita agendada o cambiada hace menos que esto acaba de recibir su correo #7.
_CITA_RECIENTE = timedelta(hours=24)

# Actividad del egresado que mueve el ancla del recordatorio de documentos.
_ACTIVIDAD_DOCS = ("document_uploaded", "document_rejected")

_CUERPO_ENCUESTA = "Sin ella no puedes agendar tu cita de cotejo."


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _aislado(db: Session, kind: str, process_id: int, paso, *args) -> bool:
    """`paso(*args)` —el correo de UN candidato y, si es nuevo, su aviso— en
    su propio SAVEPOINT. `True` = los dos quedaron en la transacción.

    Nunca lanza. Si `paso` revienta, el SAVEPOINT se deshace (correo y aviso
    juntos) y el barrido sigue. Si el flush del aviso falló, `notify_student`
    se traga el error pero Postgres ya deshizo el SAVEPOINT, y con él el
    correo: eso se ve en `is_active` y tampoco cuenta.
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
    except Exception:
        logger.exception("[titulatec] Recordatorio %s del proceso %s: no se encoló; se "
                         "reintenta en la corrida siguiente", kind, process_id)
        return False


def _llaves(db: Session, kind: str, pids: list) -> dict:
    """`{process_id: [dedupe_key]}` de las filas `kind` de esos procesos, en UNA
    consulta."""
    from itcj2.apps.titulatec.models import EmailOutbox

    out: dict[int, list[str]] = defaultdict(list)
    for pid, llave in (db.query(EmailOutbox.process_id, EmailOutbox.dedupe_key)
                       .filter(EmailOutbox.kind == kind,
                               EmailOutbox.process_id.in_(pids),
                               EmailOutbox.dedupe_key.isnot(None))):
        out[pid].append(llave)
    return out


def _enviados(llaves: dict, kind: str, pid: int, ancla: datetime) -> int:
    """Recordatorios `kind` ya encolados para ESA ancla: las llaves
    `{kind}:{pid}:{ancla:%Y%m%dT%H%M%S}:{n}` que escribe `StudentMail`. Cuentan
    todas, salieran o no: cada una ya ocupó su lugar en la cadencia."""
    prefijo = f"{kind}:{pid}:{ancla:%Y%m%dT%H%M%S}:"
    return sum(1 for llave in llaves.get(pid, ()) if llave.startswith(prefijo))


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
    AppointmentService._notify_appt(db, proc.id, "APPOINTMENT_REMINDER", titulo,
                                    appt.scheduled_at, appt.location)
    return True


def _recordar_documentos(db: Session, proc, ancla: datetime, indice: int, fase: int,
                         faltan: list, corregir: list) -> bool:
    """#10. El aviso nombra lo que falta y lo que hay que corregir."""
    from itcj2.apps.titulatec.services.mail_compose import asunto_recordatorio_documentos
    from itcj2.apps.titulatec.services.notify import notify_student
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.docs_reminder(db, proc, anchor=ancla, index=indice):
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


def _recordar_encuesta(db: Session, proc, ancla: datetime, indice: int) -> bool:
    """#11."""
    from itcj2.apps.titulatec.services.mail_compose import ASUNTO_RECORDATORIO_ENCUESTA
    from itcj2.apps.titulatec.services.notify import notify_student
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if not StudentMail.survey_reminder(db, proc, anchor=ancla, index=indice):
        return False
    notify_student(db, proc.student_id, type="SURVEY_REMINDER",
                   title=ASUNTO_RECORDATORIO_ENCUESTA, body=_CUERPO_ENCUESTA,
                   process_id=proc.id, phase_number=PhaseService.PHASE_COTEJO)
    return True


class MailReminders:
    """Barrido diario de recordatorios. Contrato completo en el docstring del
    módulo."""

    @staticmethod
    def due_index(anchor: datetime, now: datetime, sent: int) -> int | None:
        """Índice del recordatorio que toca encolar para `anchor` (== `sent`, los
        ya encolados para ella) o `None`. Toca si `sent < max_reminders()` y
        `now >= anchor + first_days() + sent * every_days()` (en días)."""
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if sent >= MailSettings.max_reminders():
            return None
        vence = anchor + timedelta(days=MailSettings.first_days()
                                   + sent * MailSettings.every_days())
        return sent if now >= vence else None

    @staticmethod
    def run(db: Session, *, now: datetime | None = None) -> dict:
        """Una corrida: `{"disabled": True}` con el correo apagado; si no,
        cuántos recordatorios NUEVOS encoló de cada tipo:
        `{"appt": n, "docs": n, "survey": n}`."""
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if not MailSettings.enabled():
            return {"disabled": True}
        now = now or db_now()
        out = {}
        for clave, barrido in (("appt", MailReminders._citas),
                               ("docs", MailReminders._documentos),
                               ("survey", MailReminders._encuestas)):
            out[clave] = barrido(db, now)
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
        """#10: procesos con su inicio de fase, documentos, nombres, actividad y
        llaves, cinco consultas para todos."""
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

        # El criterio de `initial_docs_summary` para todos a la vez: sin fila =
        # falta; `rejected` = por corregir. Nombres del catálogo (sin
        # `is_active`, como allá), o el código si no hay fila.
        codigos = DocumentService.INITIAL_DOC_TYPES
        estados: dict[int, dict[str, str]] = defaultdict(dict)
        for pid, codigo, estado in (db.query(Document.process_id, Document.type_code,
                                             Document.review_status)
                                    .filter(Document.process_id.in_([p.id for p, _ in filas]),
                                            Document.type_code.in_(codigos))):
            estados[pid][codigo] = estado
        nombres = dict(db.query(DocumentType.code, DocumentType.name)
                       .filter(DocumentType.code.in_(codigos)).all())

        pendientes = {}
        for proc, inicio in filas:
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
                ancla, now, _enviados(llaves, "docs_reminder", pid, ancla))
            if indice is not None:
                n += _aislado(db, "docs_reminder", pid, _recordar_documentos,
                              db, proc, ancla, indice, fase, faltan, corregir)
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
                ancla, now, _enviados(llaves, "survey_reminder", proc.id, ancla))
            if indice is not None:
                n += _aislado(db, "survey_reminder", proc.id, _recordar_encuesta,
                              db, proc, ancla, indice)
        return n
