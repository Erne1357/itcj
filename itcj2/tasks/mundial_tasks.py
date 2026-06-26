"""Tarea Celery: refresco diario de partidos del Mundial 2026 (cache Redis)."""
import logging

from itcj2.celery_app import celery_app
from itcj2.tasks.base import LoggedTask
from itcj2.database import SessionLocal

logger = logging.getLogger(__name__)

TASK_DEFINITIONS = [
    {
        "task_name": "itcj2.tasks.mundial_tasks.refresh_mundial_matches",
        "display_name": "Refresco de Partidos del Mundial",
        "description": (
            "Refresca el cache en Redis de los partidos del Mundial 2026 (calendario + "
            "marcadores si la API está habilitada). Se autoapaga si el tema Mundial no está activo."
        ),
        "app_name": "core",
        "category": "maintenance",
        "default_args": {},
    },
]


def _do_refresh() -> dict:
    """Cuerpo de la tarea (función plana para testear sin Celery)."""
    from itcj2.core.services import mundial_service

    with SessionLocal() as db:
        if not mundial_service.is_theme_active(db):
            mundial_service.clear_cache()
            mundial_service.sync_periodic_task(db)  # deja is_active=False
            logger.info("[mundial] tema inactivo — cache limpiado y cron apagado")
            return {"skipped": "theme_inactive"}

    # get_today_cached usa solo Redis; no necesita la sesión DB de arriba.
    today = mundial_service.get_today_cached(force=True)
    count = len(today.get("matches", []))
    logger.info("[mundial] cache refrescado — %d partidos hoy (%s)", count, today.get("date"))
    return {
        "date": today.get("date"),
        "matches_count": count,
        "provider": mundial_service.get_provider_name(),
    }


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="itcj2.tasks.mundial_tasks.refresh_mundial_matches",
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=60,
    time_limit=90,
)
def refresh_mundial_matches(self, task_run_id: int | None = None) -> dict:
    """Refresca mundial:today/mundial:fixtures en Redis. Se autoapaga si el tema no está activo."""
    return _do_refresh()
