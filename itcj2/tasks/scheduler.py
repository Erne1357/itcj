"""
DatabaseScheduler — Celery Beat scheduler que lee los schedules desde PostgreSQL.

Lee la tabla core_periodic_tasks cada CELERY_BEAT_SYNC_EVERY segundos (default 30).
Cualquier cambio hecho en la UI (activar/pausar/editar cron) se aplica sin reiniciar
el contenedor celery-beat.

Uso en entrypoint:
    celery -A itcj2.celery_app beat --scheduler itcj2.tasks.scheduler:DatabaseScheduler
"""
import logging
from datetime import datetime, timezone

from celery.beat import Scheduler, ScheduleEntry
from celery.schedules import crontab

logger = logging.getLogger(__name__)

# Cuántos segundos esperar entre recargas de la DB (configurable por env)
_DEFAULT_SYNC_EVERY = 30


def _parse_cron(expression: str) -> crontab:
    """Convierte una expresión cron de 5 campos a un objeto crontab de Celery.

    Formato: "minuto hora día_mes mes día_semana"
    Ejemplos:
        "0 3 * * *"    → cada día a las 3:00
        "0 8 * * 1"    → cada lunes a las 8:00
        "*/5 * * * *"  → cada 5 minutos
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expresión cron inválida (requiere 5 campos): '{expression}'")
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DatabaseScheduler(Scheduler):
    """Scheduler de Celery Beat que lee PeriodicTask de PostgreSQL.

    Recarga la tabla periódicamente para detectar cambios en la UI sin
    necesidad de reiniciar el contenedor.
    """

    # Segundos entre recargas de la tabla PeriodicTask
    sync_every: int = _DEFAULT_SYNC_EVERY

    def __init__(self, *args, **kwargs):
        self._db_entries: dict = {}       # task_name → ScheduleEntry activa
        self._last_db_reload: datetime | None = None
        self._dirty = True                # Fuerza recarga al arrancar
        super().__init__(*args, **kwargs)
        logger.info("[DatabaseScheduler] Iniciado. sync_every=%ds", self.sync_every)

    # ------------------------------------------------------------------
    # Overrides del ciclo de vida de Scheduler
    # ------------------------------------------------------------------

    def setup_schedule(self):
        """Llamado al arrancar Beat. Carga schedules iniciales desde la DB."""
        self._reload_from_db()

    def tick(self, *args, **kwargs):
        """Override del loop de tick para recargar schedules periódicamente."""
        now = _utcnow()
        if self._last_db_reload is None or (now - self._last_db_reload).total_seconds() >= self.sync_every:
            self._reload_from_db()
            self._last_db_reload = now

        return super().tick(*args, **kwargs)

    @property
    def schedule(self) -> dict:
        """Devuelve el diccionario de entradas activo para Celery Beat."""
        return self._db_entries

    @schedule.setter
    def schedule(self, value):
        # Celery Beat intenta asignar esto al iniciar; lo ignoramos.
        pass

    # ------------------------------------------------------------------
    # Lógica de recarga desde PostgreSQL
    # ------------------------------------------------------------------

    def _reload_from_db(self):
        """Lee core_periodic_tasks y reconstruye el schedule activo."""
        try:
            from itcj2.database import SessionLocal
            from itcj2.core.models.task_models import PeriodicTask

            with SessionLocal() as db:
                active_tasks = (
                    db.query(PeriodicTask)
                    .filter(PeriodicTask.is_active == True)  # noqa: E712
                    .all()
                )

                new_entries: dict = {}
                for pt in active_tasks:
                    try:
                        entry = self._make_entry(pt)
                        if entry:
                            new_entries[pt.name] = entry
                    except Exception as e:
                        logger.error(
                            "[DatabaseScheduler] Error procesando PeriodicTask '%s': %s",
                            pt.name, e,
                        )

            # Detectar cambios para logging
            added = set(new_entries) - set(self._db_entries)
            removed = set(self._db_entries) - set(new_entries)
            if added:
                logger.info("[DatabaseScheduler] Nuevas tareas programadas: %s", list(added))
            if removed:
                logger.info("[DatabaseScheduler] Tareas removidas del schedule: %s", list(removed))

            self._db_entries = new_entries
            logger.debug("[DatabaseScheduler] Schedule recargado: %d tareas activas.", len(new_entries))

        except Exception as e:
            logger.error("[DatabaseScheduler] Error recargando desde DB: %s", e)

    def _make_entry(self, pt) -> ScheduleEntry | None:
        """Construye un ScheduleEntry de Celery a partir de un PeriodicTask."""
        try:
            schedule = _parse_cron(pt.cron_expression)
        except ValueError as e:
            logger.warning("[DatabaseScheduler] '%s' tiene cron inválido: %s", pt.name, e)
            return None

        # Los kwargs que se pasan a la tarea. task_run_id se inyecta en apply_async
        # mediante el método apply_entry override (ver más abajo).
        kwargs = dict(pt.kwargs_json or {})
        args = list(pt.args_json or [])

        return ScheduleEntry(
            name=pt.name,
            task=pt.task_name,
            schedule=schedule,
            args=args,
            kwargs=kwargs,
            options={"periodic_task_id": pt.id},
            app=self.app,
        )

    # ------------------------------------------------------------------
    # Hook: crear TaskRun antes de encolar la tarea periódica
    # ------------------------------------------------------------------

    def apply_entry(self, entry: ScheduleEntry, producer=None):
        """Override para crear un TaskRun antes de encolar cada tarea programada."""
        import uuid
        try:
            from itcj2.database import SessionLocal
            from itcj2.core.models.task_models import TaskDefinition, TaskRun, PeriodicTask
        except ImportError as e:
            logger.error("[DatabaseScheduler] Error importando modelos en apply_entry: %s", e)
            return super().apply_entry(entry, producer=producer)

        task_run_id = None
        
        try:
            celery_id = str(uuid.uuid4())
            
            with SessionLocal() as db:
                periodic_task_id = entry.options.get("periodic_task_id")

                defn = db.query(TaskDefinition).filter_by(task_name=entry.task).first()
                display_name = defn.display_name if defn else entry.task

                run = TaskRun(
                    celery_task_id=celery_id,
                    task_name=entry.task,
                    display_name=display_name,
                    status="PENDING",
                    trigger="SCHEDULED",
                    periodic_task_id=periodic_task_id,
                    args_json=dict(entry.kwargs or {}),
                    created_at=_utcnow(),
                )
                db.add(run)
                db.commit()
                db.refresh(run)
                task_run_id = run.id

                # Actualizar last_run_at en el PeriodicTask
                if periodic_task_id:
                    # Usar update() para evitar lock/refresh issues
                    db.query(PeriodicTask).filter(PeriodicTask.id == periodic_task_id).update(
                        {"last_run_at": _utcnow()}
                    )
                    db.commit()

        except Exception as e:
            logger.error("[DatabaseScheduler] Error creando TaskRun para '%s': %s", entry.task, e)
            # No re-lanzamos la excepción para permitir que la tarea se intente encolar de todos modos
            # (aunque sin tracking en TaskRun)

        # Inyectar task_run_id en kwargs antes de encolar si se creó exitosamente
        if task_run_id:
            try:
                new_kwargs = {**dict(entry.kwargs or {}), "task_run_id": task_run_id}
                entry = ScheduleEntry(
                    name=entry.name,
                    task=entry.task,
                    schedule=entry.schedule,
                    args=entry.args,
                    kwargs=new_kwargs,
                    options=entry.options,
                    last_run_at=entry.last_run_at,
                    total_run_count=entry.total_run_count,
                    app=self.app,
                )
            except Exception as e:
                logger.error("[DatabaseScheduler] Error inyectando task_run_id: %s", e)

        # Llamar al método original de Celery Beat para encolar la tarea
        try:
            return super().apply_entry(entry, producer=producer)
        except Exception as e:
            logger.critical("[DatabaseScheduler] CRITICAL error en super().apply_entry para '%s': %s", entry.task, e)
            # Capturamos para no matar el proceso Beat

