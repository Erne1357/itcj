"""`spawn()`: corrutinas fire-and-forget que no se pierden en silencio (plan Fase 5b).

Un `loop.create_task(coro)` sin guardar la tarea falla de dos formas que
nadie ve:

- El loop solo guarda referencias DÉBILES a sus tareas. Una tarea suspendida
  en un futuro que nadie más referencia es basura para el recolector, que la
  destruye A MEDIO VUELO ("Task was destroyed but it is pending!", medido en
  el contenedor de dev): el push nunca sale y no queda rastro.
- Si la corrutina revienta, la excepción solo aparece cuando el recolector
  destruye la tarea ("Task exception was never retrieved"), por el logger de
  asyncio, sin `request_id` y sin decir qué sitio la lanzó.

`spawn(coro, name=...)` guarda la tarea en un set de módulo hasta que termina.
Al terminar la saca del set, loguea la excepción (ERROR, traceback en la
misma línea JSON) con el contexto de QUIEN la lanzó y cuenta
`itcj_background_tasks_total{name,status}`.

El contexto de origen llega solo: `add_done_callback` sin `context=` corre el
callback en una COPIA del contexto vigente al registrarlo, el del llamador
(la petición). Esa copia sigue viva aunque la petición ya haya respondido y
reseteado sus ids, y no ve lo que la tarea haya ligado por dentro.

`name` es el SITIO técnico (R37: `async_broadcast`, `notify_websocket_push`),
no el evento de negocio, para no tocar los ~30 llamadores de
`async_broadcast`; el evento va en la línea de log (el nombre de la
corrutina). Un `name` fuera del conjunto cerrado sigue la política de
`work.closed_label_ok()`: ValueError en desarrollo y tests; en producción la
tarea corre igual, sin contarse, y se avisa una vez.

`status`: `ok`, `error`, `cancelled` (R38: aparte de `error`, porque el
apagado del loop en un swap blue-green cancela lo pendiente y no debe
ensuciar el panel de errores) y `dropped` (`discard()`: la rama de
`async_broadcast` sin loop).

Solo para trabajo CORTO. Las tareas de vida larga (el subscriber de Redis, la
sonda de lag) siguen con su `create_task` y su referencia en el lifespan: su
final es el apagado, no un resultado que contar.

Regla de oro 1: nada de `metrics` ni `prometheus_client` al importar. Este
módulo lo carga `itcj2.utils`, al que importan servicios que también corren
en Celery: se reutiliza el import perezoso y guardado de `work.load_metrics()`.
Regla de oro 2: la tarea es la misma y devuelve lo mismo, y nada de la
instrumentación lanza desde el done-callback.
"""
import asyncio
import logging
from functools import partial

from itcj2.observability.work import closed_label_ok, load_metrics, report_metrics_failure

logger = logging.getLogger(__name__)

# Conjuntos cerrados de etiquetas (contrato de la ronda 2). Aquí y no en
# `metrics.py`, como los de `work.py`: la validación no puede depender de un
# import que en Celery puede fallar.
BACKGROUND_TASK_NAMES = frozenset({"async_broadcast", "notify_websocket_push"})
BACKGROUND_TASK_STATUSES = frozenset({"ok", "error", "dropped", "cancelled"})

_METRIC = "itcj_background_tasks_total"

# Las referencias fuertes a las tareas en vuelo. Cada tarea se saca en su
# done-callback, así que el set solo tiene lo que sigue corriendo. Sin candado:
# todo lo que lo toca corre en el hilo de su loop (`async_broadcast` salta al
# loop ANTES de llamar a `spawn`), y `add`/`discard` de un set son atómicos
# con el GIL aunque haya un loop por hilo (los tests abren varios).
_tasks: set = set()


def _close(coro) -> None:
    """Cierra una corrutina que no va a correr: sin esto, al recolectarla sale
    "RuntimeWarning: coroutine ... was never awaited", ruido que tapa el
    motivo real."""
    close = getattr(coro, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass


def _describe(coro) -> str:
    """El nombre de la corrutina (p. ej. `broadcast_ticket_created`): el
    evento de negocio que la etiqueta `name` no lleva (R37)."""
    return getattr(coro, "__qualname__", None) or type(coro).__name__


def _count(name: str, status: str) -> None:
    """Suma uno a `itcj_background_tasks_total`. Nunca lanza."""
    try:
        metrics = load_metrics()
        if metrics is not None:
            metrics.BACKGROUND_TASKS.labels(name=name, status=status).inc()
    except Exception:
        try:
            report_metrics_failure("BACKGROUND_TASKS")
        except Exception:
            pass


def _on_done(task: asyncio.Task, *, name: str, coroutine: str, counted: bool) -> None:
    # Primero soltar la referencia: pase lo que pase después, el set no crece.
    _tasks.discard(task)
    try:
        if task.cancelled():
            status = "cancelled"
        else:
            # Leerla la marca como recuperada: asyncio ya no repite el
            # "Task exception was never retrieved" sin contexto.
            exc = task.exception()
            status = "ok" if exc is None else "error"
            if exc is not None:
                logger.error(
                    "%s: la corrutina %s terminó con una excepción",
                    name, coroutine,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
        if counted:
            _count(name, status)
    except Exception:
        # Un done-callback que lanza acaba en el manejador de excepciones del
        # loop como "Exception in callback": la instrumentación no llega ahí.
        pass


def spawn(coro, *, name: str) -> asyncio.Task:
    """Lanza `coro` como tarea en el loop que corre en este hilo, con
    referencia fuerte hasta que termine, log de su excepción y cuenta de su
    resultado. Regresa la tarea (la misma que daría `create_task`).

    Sin loop corriendo lanza `RuntimeError`, como `asyncio.create_task`, y un
    `name` fuera del conjunto cerrado lanza `ValueError` en desarrollo. En
    los dos casos la corrutina se cierra antes: no va a correr.
    """
    try:
        loop = asyncio.get_running_loop()
        counted = closed_label_ok(_METRIC, "name", name, BACKGROUND_TASK_NAMES)
        task = loop.create_task(coro)
    except BaseException:
        _close(coro)
        raise
    _tasks.add(task)
    task.add_done_callback(
        partial(_on_done, name=name, coroutine=_describe(coro), counted=counted)
    )
    return task


def discard(coro, *, name: str) -> None:
    """Descarta `coro` sin correrla: la cierra y cuenta `status="dropped"`."""
    _close(coro)
    if closed_label_ok(_METRIC, "name", name, BACKGROUND_TASK_NAMES):
        _count(name, "dropped")
