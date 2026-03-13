"""
Clase base LoggedTask para todas las tareas Celery de itcj2.

Cualquier tarea que herede de LoggedTask registra automáticamente
su ejecución en la tabla core_task_runs de PostgreSQL.

Flujo de uso:
    1. La API crea un TaskRun con status=PENDING y obtiene su id
    2. La API llama task.apply_async(kwargs={"task_run_id": run.id}, task_id=run.celery_task_id)
    3. before_start()  → actualiza TaskRun a RUNNING
    4. Cuerpo de la tarea ejecuta la lógica de negocio
    5. on_success()    → actualiza TaskRun a SUCCESS con result_json
       on_failure()    → actualiza TaskRun a FAILURE con error_json

Al terminar (success o failure) se publica un evento en Redis Pub/Sub
para que el backend Uvicorn lo retransmita por Socket.IO al usuario.
"""
import json
import logging
from datetime import datetime

from celery import Task


def _now() -> datetime:
    """Hora local del servidor (igual que NOW() en la base de datos)."""
    return datetime.now()

logger = logging.getLogger(__name__)


class LoggedTask(Task):
    """Task base que persiste el historial de ejecución en TaskRun."""

    abstract = True

    # ------------------------------------------------------------------ #
    # Hooks del ciclo de vida                                              #
    # ------------------------------------------------------------------ #

    def before_start(self, task_id, args, kwargs):
        """Marca el TaskRun como RUNNING justo antes de ejecutar."""
        task_run_id = kwargs.get("task_run_id")
        if not task_run_id:
            return
        self._update_run(task_run_id, {
            "status": "RUNNING",
            "celery_task_id": task_id,
            "started_at": _now(),
        })

    def on_success(self, retval, task_id, args, kwargs):
        """Marca el TaskRun como SUCCESS, guarda el resultado y notifica vía Redis."""
        task_run_id = kwargs.get("task_run_id")
        if not task_run_id:
            return
        finished = _now()
        update = {
            "status": "SUCCESS",
            "result_json": retval if isinstance(retval, dict) else {"result": str(retval)},
            "finished_at": finished,
            "progress": 100,
        }
        user_id = self._update_run(task_run_id, update, calc_duration=True)
        self._publish_task_event(task_run_id, "SUCCESS", self.name, user_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Marca el TaskRun como FAILURE, guarda el traceback y notifica vía Redis."""
        task_run_id = kwargs.get("task_run_id")
        if not task_run_id:
            return
        update = {
            "status": "FAILURE",
            "result_json": {
                "error": str(exc),
                "traceback": str(einfo) if einfo else None,
            },
            "finished_at": _now(),
        }
        user_id = self._update_run(task_run_id, update, calc_duration=True)
        self._publish_task_event(task_run_id, "FAILURE", self.name, user_id)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Registra el reintento en el progress_message del TaskRun."""
        task_run_id = kwargs.get("task_run_id")
        if not task_run_id:
            return
        self._update_run(task_run_id, {
            "progress_message": f"Reintentando tras error: {exc}",
        })

    # ------------------------------------------------------------------ #
    # Helper para actualizar el progreso desde el cuerpo de la tarea      #
    # ------------------------------------------------------------------ #

    def update_progress(self, task_run_id: int, current: int, total: int, message: str = ""):
        """Actualiza el progreso de un TaskRun desde el cuerpo de la tarea.

        Uso:
            self.update_progress(task_run_id, current=45, total=200, message="Procesando...")
        """
        if not task_run_id:
            return
        progress = int((current / total) * 100) if total > 0 else 0
        self._update_run(task_run_id, {
            "progress": progress,
            "progress_message": message or f"{current}/{total}",
        })

    # ------------------------------------------------------------------ #
    # Acceso a la DB (sesión propia para no depender del contexto Uvicorn) #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _update_run(
        task_run_id: int,
        fields: dict,
        calc_duration: bool = False,
    ) -> int | None:
        """Abre su propia sesión SQLAlchemy para actualizar TaskRun.

        Usa una sesión corta (abre y cierra) para ser compatible con
        pgBouncer en modo transaction-pooling.

        Returns:
            triggered_by_user_id del TaskRun, o None si no aplica.
        """
        try:
            from itcj2.database import SessionLocal
            from itcj2.core.models.task_models import TaskRun

            with SessionLocal() as db:
                run = db.get(TaskRun, task_run_id)
                if not run:
                    return None

                for key, value in fields.items():
                    setattr(run, key, value)

                if calc_duration and run.started_at and run.finished_at:
                    delta = run.finished_at - run.started_at
                    run.duration_seconds = round(delta.total_seconds(), 3)

                db.commit()
                return run.triggered_by_user_id

        except Exception as e:
            logger.error(f"LoggedTask: no se pudo actualizar TaskRun {task_run_id}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Redis Pub/Sub — puente worker → Uvicorn → Socket.IO                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _publish_task_event(
        task_run_id: int,
        status: str,
        task_name: str,
        user_id: int | None,
    ) -> None:
        """Publica un evento de finalización en Redis para que Uvicorn
        lo retransmita por Socket.IO al usuario que disparó la tarea.

        Solo publica si hay un user_id (tareas manuales). Las tareas
        programadas por Beat no tienen usuario directo.
        """
        if not user_id:
            return
        try:
            import redis
            from itcj2.config import get_settings

            r = redis.from_url(get_settings().REDIS_URL)
            r.publish("task_events", json.dumps({
                "type": "task_completed",
                "task_run_id": task_run_id,
                "task_name": task_name,
                "status": status,
                "user_id": user_id,
            }))
        except Exception as e:
            logger.error(
                "LoggedTask: no se pudo publicar en Redis task_events "
                f"(task_run_id={task_run_id}): {e}"
            )
