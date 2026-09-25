"""Tareas Celery de TitulaTec — elegibilidad automática contra el SII.

Spec 2026-09-25 §3.4. Solo hacen algo en el modo `sii`
(`TITULATEC_ENROLLMENT_REVIEWER`); en los otros modos el servicio es un no-op.

Tareas:
    sii_check_request(req_id, attempt=1, force=False)
        Consulta al SII UNA solicitud. La encola `EnrollmentRequestService.create`
        tras el commit del alta (`eligibility_service.enqueue_check`, por nombre).
        Ante `error` reintenta con espera creciente hasta
        `EligibilityService.max_attempts()`; cada reintento es un intento nuevo
        (fila nueva en `titulatec_eligibility_checks`). La idempotencia (dos
        tareas del mismo `req_id`, la tarea que llega antes que el alta) vive en
        `EligibilityService.check`, no aquí.

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

# Metadata para `core_task_definitions` (patrón de los otros módulos). La
# consulta por solicitud es interna (la dispara el alta): no se cataloga.
TASK_DEFINITIONS: list[dict] = []


def _backoff(attempt: int) -> int:
    """Segundos de espera antes del intento `attempt + 1`."""
    return min(_BACKOFF_BASE_S * 2 ** max(attempt - 1, 0), _BACKOFF_MAX_S)


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="itcj2.tasks.titulatec_tasks.sii_check_request",
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

    if out["status"] == "error" and out["attempt"] < EligibilityService.max_attempts():
        logger.info("SII: la consulta de la solicitud %s falló (intento %s); se reintenta",
                    req_id, out["attempt"])
        raise self.retry(
            kwargs={"req_id": req_id, "attempt": out["attempt"] + 1, "force": False},
            countdown=_backoff(out["attempt"]),
        )
    return out
