"""
Factory de la aplicación Celery para itcj2.

Uso:
    from itcj2.celery_app import celery_app

Los workers se arrancan desde Docker con:
    celery -A itcj2.celery_app worker --loglevel=info
"""
from celery import Celery
from celery.signals import setup_logging, worker_process_init, worker_process_shutdown

from itcj2.config import get_settings
from itcj2.observability.logging_config import configure_logging

# Efecto lateral: conecta los receptores que llevan el contexto de la petición
# a la tarea (Fase 5a). Aquí porque TODO proceso que encola o ejecuta tareas
# importa esta app: los HTTP que publican, el worker y el beat. Quitar esta
# línea apaga la propagación entera (palanca de rollback de 5a).
import itcj2.observability.celery_hooks  # noqa: F401


@setup_logging.connect
def _configure_logging(**kwargs) -> None:
    """Logs del worker y del beat en el mismo formato que la app (R10).

    Por la señal y no con una llamada suelta al importar este módulo: al
    arrancar, Celery vacía `root.handlers` (`worker_hijack_root_logger`, activo
    por defecto) y pone su propio formato de texto, salvo que haya un receptor
    conectado a `setup_logging`, en cuyo caso deja todo el logging en sus
    manos. Con un receptor tampoco redirige stdout/stderr al logger.

    `--loglevel` del CLI de Celery (en `kwargs`) se ignora a propósito: manda
    `LOG_LEVEL`, igual que en la app.
    """
    configure_logging()


@worker_process_init.connect
def _setup_tracing(**kwargs) -> None:
    """Trazas OTel (Fase 7) en CADA hijo del prefork, solo con OTEL_ENABLED=1.

    Nunca al importar ni en el proceso padre: el hilo del `BatchSpanProcessor`
    y el canal gRPC del exportador no sobreviven al `fork`, y un hijo que los
    heredara encolaría spans que nadie manda. El import es perezoso por la
    misma regla que el resto de la cadena de Celery.
    """
    from itcj2.observability.tracing import setup_tracing

    setup_tracing(role="celery")


@worker_process_shutdown.connect
def _shutdown_tracing(**kwargs) -> None:
    """Vacía el batch de spans al morir el hijo (reinicio, `max_tasks`)."""
    from itcj2.observability.tracing import shutdown_tracing

    shutdown_tracing()


def create_celery_app() -> Celery:
    settings = get_settings()

    app = Celery(
        "itcj2",
        broker=settings.REDIS_URL,
        # No usamos result backend de Celery; el historial se guarda
        # en PostgreSQL mediante el modelo TaskRun (ver itcj2/tasks/base.py).
        backend=settings.REDIS_URL,
        include=[
            "itcj2.tasks.helpdesk_tasks",
            "itcj2.tasks.notification_tasks",
            "itcj2.tasks.mundial_tasks",
            "itcj2.tasks.titulatec_tasks",
        ],
    )

    app.conf.update(
        # Serialización
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Tiempo — sin UTC para que coincida con la zona horaria del servidor y la DB
        timezone=settings.APP_TZ,
        enable_utc=False,
        # Comportamiento de tareas
        task_track_started=True,       # El worker reporta STARTED antes de ejecutar
        task_acks_late=True,           # Reconoce la tarea solo al terminar (resiste crashes)
        worker_prefetch_multiplier=1,  # Una tarea a la vez por worker (evita monopolización)
        # Resultados en Redis: TTL corto (solo para Celery internals, el historial real está en DB)
        result_expires=3600,
        # Colas
        task_default_queue="default",
        task_queues={
            "default": {"exchange": "default", "routing_key": "default"},
            "reports": {"exchange": "reports", "routing_key": "reports"},
            "notifications": {"exchange": "notifications", "routing_key": "notifications"},
        },
        task_routes={
            "itcj2.tasks.helpdesk_tasks.export_inventory_report": {"queue": "reports"},
            "itcj2.tasks.notification_tasks.send_mass_notification": {"queue": "notifications"},
        },
    )

    return app


celery_app = create_celery_app()
