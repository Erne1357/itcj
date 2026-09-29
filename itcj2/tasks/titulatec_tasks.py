"""Tareas Celery de TitulaTec — elegibilidad contra el SII y correos del
proceso al egresado.

Las del SII (spec 2026-09-25 §3.4) solo hacen algo en el modo `sii`
(`TITULATEC_ENROLLMENT_REVIEWER`) y con el SII configurado
(`TITULATEC_SII_BACKEND` distinto de `disabled`, spec 2026-09-27 D11); si no,
el servicio es un no-op.

Tareas (nombres del spec, `titulatec.*`: `enqueue_check` y el DML de las
periódicas las mandan por NOMBRE, no por ruta de módulo):
    titulatec.sii_check_request(req_id, attempt=1, force=False)
        Consulta al SII UNA solicitud. La encola `EnrollmentRequestService.create`
        tras el commit del alta (`eligibility_service.enqueue_check`, por nombre).
        Ante un `error` REINTENTABLE (`chk.retryable`: el SII no respondió,
        `SiiUnavailable`; spec §3.4) reintenta con espera creciente hasta
        `EligibilityService.max_attempts()`; cada reintento es un intento nuevo
        (fila nueva en `titulatec_eligibility_checks`). Un error de
        configuración (reglas, consulta inválida) no se reintenta. La
        idempotencia (dos tareas del mismo `req_id`, la tarea que llega antes
        que el alta) vive en `EligibilityService.check`, no aquí.

    titulatec.sii_sweep()
        Periódica (Celery Beat vía `DatabaseScheduler`, cada 10 min; alta por
        el DML `sii_2026_09/16_insert_sii_sweep_task.sql` de `init-titulatec`).
        Recoge lo que quedó sin consultar y reintenta los errores
        (`EligibilityService.sweep`). No aprueba nada: toda solicitud la
        aprueba Servicios Escolares desde la bandeja (spec 2026-09-27). Con el
        SII sin configurar (`TITULATEC_SII_BACKEND=disabled`, D11) no toca la
        BD y devuelve sus conteos en cero con `"disabled": True`. A mano:
        `titulatec sii-sweep`.

        La descripción de esta tarea en `core_task_definitions` la sembró el
        DML `sii_2026_09/16` y todavía dice «aprueba las aptas»: texto legado
        de la BD (Ruling R6, no se re-siembra); la de `TASK_DEFINITIONS`,
        abajo, ya es la vigente.

    titulatec.email_dispatch()
        Periódica, cada 5 minutos (`*/5 * * * *`, spec 2026-09-28 §6 C3/C5,
        ruling 18; su alta en `core_periodic_tasks` es un DML aparte). Manda
        los correos pendientes de `titulatec_email_outbox`
        (`MailDispatcher.run`: grupos con su espera, re-validación,
        destinatario, Graph y reintentos) y devuelve cuántos correos
        terminaron en cada desenlace. Con `TITULATEC_EMAIL_ENABLED=false` no
        toca la BD y devuelve `{"disabled": True}`. Una corrida sin movimiento
        va al log en DEBUG, no en INFO: corre 288 veces al día.

    titulatec.email_reminders()
        Periódica, diaria a las 9:00 (spec 2026-09-28 §6 C4/C5; su alta en
        `core_periodic_tasks` es un DML aparte). Encola los recordatorios que
        tocan hoy —la cita de cotejo del día siguiente, los documentos que
        faltan o hay que corregir, la encuesta de egresados— con su aviso
        in-app (`MailReminders.run`); los manda `email_dispatch`. Idempotente:
        correrla dos veces no duplica correos ni avisos. Devuelve
        `{"appt", "docs", "survey"}` (recordatorios nuevos de cada tipo) o
        `{"disabled": True}` con el correo apagado.

La lógica vive en los services (`EligibilityService`, `MailDispatcher`,
`MailReminders`); aquí solo sesión, reintento y resultado. `SessionLocal` se
importa DENTRO de cada tarea (los tests lo parchean).
"""
import logging

from itcj2.celery_app import celery_app
from itcj2.tasks.base import LoggedTask

logger = logging.getLogger(__name__)

# Tope de la espera entre reintentos (1 min, 2, 4, 8, … hasta 1 h).
_BACKOFF_BASE_S = 60
_BACKOFF_MAX_S = 3600

# Presupuesto del barrido: deja de tomar solicitudes nuevas antes de que celery
# corte la tarea (`soft_time_limit`); con la periódica cada 10 min no se enciman.
_SWEEP_BUDGET_S = 480

# Metadata para `core_task_definitions` (patrón de los otros módulos). La
# consulta por solicitud es interna (la dispara el alta): no se cataloga. El
# alta en la BD (definición + programación) es el DML
# `database/DML/titulatec/sii_2026_09/16_insert_sii_sweep_task.sql`, que corre
# con `init-titulatec` (`SEED_FILES`).
TASK_DEFINITIONS = [
    {
        "task_name": "titulatec.sii_sweep",
        "display_name": "Barrido de elegibilidad del SII (TitulaTec)",
        "description": (
            "Modo sii: consulta al SII las solicitudes de inscripción que quedaron sin "
            "consultar y reintenta las consultas fallidas (hasta "
            "TITULATEC_SII_MAX_ATTEMPTS). No aprueba nada: eso es de Servicios Escolares. "
            "En otro modo no hace nada."
        ),
        "app_name": "titulatec",
        "category": "maintenance",
        "default_args": {},
    },
    {
        "task_name": "titulatec.email_dispatch",
        "display_name": "Despacho de correos al egresado (TitulaTec)",
        "description": (
            "Cada 5 minutos: manda por correo los avisos pendientes del proceso de "
            "titulación (dictámenes, fases, GTV, citas y recordatorios) al correo "
            "personal del egresado. Agrupa los movimientos de un mismo proceso, "
            "descarta lo que ya no aplica y reintenta con espera creciente hasta "
            "TITULATEC_EMAIL_MAX_ATTEMPTS. Con TITULATEC_EMAIL_ENABLED=false no hace nada."
        ),
        "app_name": "titulatec",
        "category": "notification",
        "default_args": {},
    },
    {
        "task_name": "titulatec.email_reminders",
        "display_name": "Recordatorios por correo al egresado (TitulaTec)",
        "description": (
            "Diario: encola los recordatorios del proceso de titulación con su aviso en "
            "la app — la cita de cotejo del día siguiente "
            "(TITULATEC_APPT_REMINDER_DAYS_BEFORE), los documentos iniciales que faltan "
            "o hay que corregir y la encuesta de egresados (a los "
            "TITULATEC_REMINDER_FIRST_DAYS días, luego cada TITULATEC_REMINDER_EVERY_DAYS, "
            "hasta TITULATEC_REMINDER_MAX). No duplica si corre dos veces; los manda el "
            "despacho de correos. Con TITULATEC_EMAIL_ENABLED=false no hace nada."
        ),
        "app_name": "titulatec",
        "category": "notification",
        "default_args": {},
    },
]


def _backoff(attempt: int) -> int:
    """Segundos de espera antes del intento `attempt + 1`."""
    return min(_BACKOFF_BASE_S * 2 ** max(attempt - 1, 0), _BACKOFF_MAX_S)


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="titulatec.sii_check_request",
    # El tope real es `EligibilityService.max_attempts()` (≤ 20 por settings);
    # este solo evita que celery corte antes.
    max_retries=20,
    soft_time_limit=600,
    time_limit=660,
)
def sii_check_request(self, req_id: int, attempt: int = 1, force: bool = False,
                      task_run_id: int | None = None) -> dict:
    """Consulta al SII la solicitud `req_id` (solo el veredicto; no la aprueba)."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        chk = EligibilityService.check(db, req_id, attempt=attempt, force=force)
        if chk is None:
            return {"req_id": req_id, "skipped": True}
        out = {"req_id": req_id, "check_id": chk.id, "status": chk.status,
               "attempt": chk.attempt}
        retryable = chk.status == "error" and bool(chk.retryable)

    if retryable and out["attempt"] < EligibilityService.max_attempts():
        logger.info("SII: el SII no respondió a la consulta de la solicitud %s "
                    "(intento %s); se reintenta", req_id, out["attempt"])
        raise self.retry(
            kwargs={"req_id": req_id, "attempt": out["attempt"] + 1, "force": False},
            countdown=_backoff(out["attempt"]),
        )
    return out


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="titulatec.sii_sweep",
    soft_time_limit=540,
    time_limit=600,
)
def sii_sweep(self, task_run_id: int | None = None) -> dict:
    """Barrido periódico del SII (`EligibilityService.sweep`): consulta y
    reintenta, nunca aprueba; devuelve `{"checked", "retried"}`. Con el SII
    sin configurar (backend `disabled`, spec 2026-09-27 D11) no toca la BD y
    devuelve los conteos en cero con `"disabled": True`."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        out = EligibilityService.sweep(db, max_seconds=_SWEEP_BUDGET_S)
    logger.info("SII: barrido — %s", out)
    return out


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="titulatec.email_dispatch",
    soft_time_limit=50,
    time_limit=58,
)
def email_dispatch(self, task_run_id: int | None = None) -> dict:
    """Despacho periódico de los correos del proceso (`MailDispatcher.run`,
    con su reloj `db_now()` y su lote por omisión). Devuelve
    `{"sent", "failed", "retry", "no_recipient", "obsolete", "waiting"}` o
    `{"disabled": True}` con el correo apagado."""
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        out = MailDispatcher.run(db)
    logger.log(logging.INFO if any(out.values()) else logging.DEBUG,
               "Correos: despacho — %s", out)
    return out


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="titulatec.email_reminders",
    soft_time_limit=540,
    time_limit=600,
)
def email_reminders(self, task_run_id: int | None = None) -> dict:
    """Barrido diario de recordatorios (`MailReminders.run`, con su reloj
    `db_now()`). Devuelve `{"appt", "docs", "survey"}` —recordatorios nuevos
    de cada tipo— o `{"disabled": True}` con el correo apagado."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        out = MailReminders.run(db)
    logger.info("Correos: recordatorios — %s", out)
    return out
