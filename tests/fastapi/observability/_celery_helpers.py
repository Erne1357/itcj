"""Helpers para probar el contexto a través de Celery (Fase 5a, Task 3).

Por qué un broker `memory://` y no `task_always_eager`/`.apply()`: en modo
eager Celery NO dispara `before_task_publish` (medido en celery 5.6.3), así que
un test eager nunca pasaría por la publicación, que es justo la mitad de lo que
se prueba. Con `memory://` y `task_always_eager=False`, `apply_async` publica
de verdad y de forma síncrona (sin worker); el mensaje se lee del broker y se
ejecuta con `celery.worker.request.Request.execute()`, la misma clase con la
que el worker arma el `task.request` desde las cabeceras del mensaje. Así
`task_prerun` recibe lo que recibiría en producción.

El transporte `memory://` de kombu guarda sus colas a nivel de CLASE (las
comparten todas las apps del proceso): cada test usa su propia cola, con
nombre único, para que un mensaje olvidado no lo consuma otro test.
"""
import uuid

from celery import Celery
from celery.worker.request import Request

# Los receptores de señales se conectan al importar `celery_hooks`; en
# producción lo importa `itcj2/celery_app.py`, que estos tests no cargan. Sin
# esta línea un módulo corrido solo publica sin cabecera y su tarea no liga
# nada: pasaba únicamente si otro módulo de la sesión ya había importado los
# hooks.
import itcj2.observability.celery_hooks  # noqa: F401


def memory_app(name: str) -> Celery:
    app = Celery(name, broker="memory://", set_as_current=False)
    app.conf.update(
        task_always_eager=False,
        # Sin backend de resultados: nada que guardar ni que limpiar.
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
    )
    return app


def unique_queue() -> str:
    return f"obs-test-{uuid.uuid4().hex}"


def consume(app: Celery, queue: str):
    """El único mensaje publicado en `queue` (falla si no hay ninguno).

    Se reconoce al leerlo: `Request.execute()` sin worker no reconoce nada en
    kombu, y al cerrar el canal un mensaje sin reconocer vuelve a la cola.
    """
    with app.connection_for_read() as conn:
        simple = conn.SimpleQueue(queue)
        try:
            message = simple.get(timeout=1)
            message.ack()
            return message
        finally:
            simple.close()


def run_as_worker(app: Celery, message):
    """Ejecuta el mensaje como lo haría el worker: `task.request` sale de sus
    cabeceras, y `task_prerun`/`task_postrun` corren alrededor del cuerpo."""
    return Request(message, app=app).execute()
