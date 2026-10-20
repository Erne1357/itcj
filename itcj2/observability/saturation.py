"""Sonda de saturación (plan Fase 3): qué recurso se agotó cuando la app se
puso lenta — el threadpool de anyio, el executor de asyncio o el pool de BD.

No hay temporizador propio: `update_gauges()` la llama cada ~5 s la sonda de
lag (`loop_lag.run_probe`), dentro del loop de CADA worker. Así los cuatro
escriben su fichero mmap y `livesum` suma la máquina entera. La muestra puede
tener hasta ~5 s de antigüedad, irrelevante a `scrape_interval: 30s`.

Tres trampas que explican la forma del código:

- `dispose()` (apagado, respawn) sustituye `engine.pool` por un pool nuevo, y
  leer el viejo NUNCA falla: devuelve para siempre sus últimos números. Por
  eso el pool se relee a través del módulo en cada ciclo, jamás se cachea.
- `current_default_thread_limiter()` solo funciona dentro de un event loop
  (fuera lanza `NoEventLoopError`): el ciclo corre en la tarea de la sonda.
- Bajo uvloop (uvicorn lo elige solo: no se pasa `--loop`) el loop no expone
  `_default_executor`. El executor de `asyncio.to_thread` solo se puede
  observar si lo instala uno mismo: `install_default_executor()`.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread

from itcj2.observability import metrics

logger = logging.getLogger("itcj2.observability")

# El que instaló `install_default_executor()` en el loop de este proceso.
_default_executor: ThreadPoolExecutor | None = None


def install_default_executor(loop) -> ThreadPoolExecutor:
    """Instala en `loop` un executor por defecto observable y lo recuerda.

    Sin `max_workers` a propósito (R7): mismo `min(32, cpu + 4)` que el
    executor que el loop crearía solo, para no cambiar la concurrencia que se
    quiere medir en el tier de sockets (`asyncio.to_thread` en
    `itcj2/sockets/`), ni el techo que su pool de BD tiene que cubrir.
    """
    global _default_executor
    executor = ThreadPoolExecutor(thread_name_prefix="itcj-default")
    loop.set_default_executor(executor)
    _default_executor = executor
    return executor


def _update_db_pool() -> None:
    # Imports locales: `itcj2.database` crea el engine e importa todos los
    # modelos; el paquete de observabilidad se importa antes que eso.
    from itcj2 import database
    from itcj2.config import get_settings

    pool = database.engine.pool  # fresco en cada ciclo: ver docstring
    metrics.DB_POOL_SIZE.set(pool.size())
    metrics.DB_POOL_CHECKEDIN.set(pool.checkedin())
    metrics.DB_POOL_CHECKEDOUT.set(pool.checkedout())
    # `overflow()` arranca en -pool_size y solo llega a positivo al prestar
    # conexiones de desborde (plan §9.12): graficado a secas es una línea
    # negativa que parece una métrica rota. La saturación se lee como
    # checkedout / (size + max_overflow); por eso `max_overflow` va aparte,
    # de la configuración (30 en HTTP, 16 en sockets, 20 en Celery): no se
    # puede derivar de `overflow()`.
    metrics.DB_POOL_OVERFLOW.set(pool.overflow())
    metrics.DB_POOL_MAX_OVERFLOW.set(get_settings().DB_MAX_OVERFLOW)


def _update_anyio_limiter() -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    metrics.ANYIO_THREADPOOL_TOTAL.set(limiter.total_tokens)
    metrics.ANYIO_THREADPOOL_BORROWED.set(limiter.borrowed_tokens)
    # > 0 es la prueba de que los endpoints `def` agotaron los hilos.
    metrics.ANYIO_THREADPOOL_WAITING.set(limiter.statistics().tasks_waiting)


def _update_default_executor() -> None:
    executor = _default_executor
    if executor is None:
        return
    metrics.ASYNCIO_THREADPOOL_TOTAL.set(executor._max_workers)
    # ThreadPoolExecutor nunca retira hilos: es la marca más alta, no los
    # ocupados. La saturación la dice `waiting` (la cola solo crece cuando
    # ya no quedan hilos libres).
    metrics.ASYNCIO_THREADPOOL_THREADS.set(len(executor._threads))
    metrics.ASYNCIO_THREADPOOL_WAITING.set(executor._work_queue.qsize())


_SOURCES = (_update_db_pool, _update_anyio_limiter, _update_default_executor)


def update_gauges() -> None:
    """Un ciclo de la sonda. Síncrono y barato (contadores en memoria, sin
    I/O). Nunca lanza: una excepción mataría la tarea de la sonda y los
    Gauges se quedarían congelados en su último valor sin que nada avise.
    Cada fuente va por separado, para que una rota no deje sin actualizar a
    las demás."""
    for update in _SOURCES:
        try:
            update()
        except Exception:
            logger.exception("sonda de saturación: falló %s", update.__name__)
