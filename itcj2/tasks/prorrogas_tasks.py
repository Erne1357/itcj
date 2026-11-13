"""Tareas Celery de Prórrogas.

    prorrogas.payment_reminders()
        Diaria a las 8:00 (alta en `core_periodic_tasks` por `08_insert_plan5.sql`).
        Recordatorio de pago a 5, 1 y 0 días del vencimiento (`ReminderService.run`).
        Idempotente: correrla dos veces el mismo día no repite avisos.
"""
import logging

from itcj2.celery_app import celery_app
from itcj2.tasks.base import LoggedTask

logger = logging.getLogger(__name__)

TASK_DEFINITIONS = [
    {
        "task_name": "prorrogas.payment_reminders",
        "display_name": "Recordatorios de pago (Prórrogas)",
        "description": (
            "Cada día avisa por correo y en la plataforma a los estudiantes con una parcialidad "
            "que vence en 5 días, 1 día o hoy. Un aviso por umbral; ninguno después del vencimiento."
        ),
        "app_name": "prorrogas_tec",
        "category": "notification",
        "default_args": {},
    },
]


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="prorrogas.payment_reminders",
    soft_time_limit=540,
    time_limit=600,
)
def payment_reminders(self, task_run_id: int | None = None) -> dict:
    """Devuelve `{"enviados", "fallidos"}`."""
    from itcj2.apps.prorrogas_tec.services.reminder_service import ReminderService
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        out = ReminderService.run(db, db_now().date())
    logger.info("Prórrogas: recordatorios de pago — %s", out)
    return out
