"""Tareas Celery de TitulaTec — elegibilidad automática contra el SII.

Spec 2026-09-25 §3.4. Solo hacen algo en el modo `sii`
(`TITULATEC_ENROLLMENT_REVIEWER`); en los otros modos el servicio es un no-op.

Tareas (nombres del spec §3.4, `titulatec.*`: `enqueue_check` y el DML de la
periódica las mandan por NOMBRE, no por ruta de módulo):
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
        Recoge lo que quedó sin consultar, reintenta los errores y aprueba las
        aptas con la ventana de veto vencida (`EligibilityService.sweep`). A
        mano: `titulatec sii-sweep`.

La lógica vive en `EligibilityService`; aquí solo sesión, reintento y resultado.
`SessionLocal` se importa DENTRO de cada tarea (los tests lo parchean).
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
            "consultar, reintenta las consultas fallidas (hasta TITULATEC_SII_MAX_ATTEMPTS) "
            "y aprueba las aptas cuya ventana de veto venció. En otro modo no hace nada."
        ),
        "app_name": "titulatec",
        "category": "maintenance",
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
    """Consulta al SII la solicitud `req_id` (y la aprueba sola si procede)."""
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
    """Barrido periódico del SII (`EligibilityService.sweep`)."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        out = EligibilityService.sweep(db, max_seconds=_SWEEP_BUDGET_S)
    logger.info("SII: barrido — %s", out)
    return out
