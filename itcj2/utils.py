"""
Utilidades compartidas para itcj2 (FastAPI).
"""
from __future__ import annotations

import asyncio
import logging

from itcj2.observability.spawn import discard, spawn, spawn_threadsafe

logger = logging.getLogger(__name__)

# Referencia al event loop principal (se establece en lifespan/startup)
_main_loop: asyncio.AbstractEventLoop | None = None

# Sitio de `itcj_background_tasks_total` (R37): el mismo para los ~30
# llamadores, que no cambian. El evento concreto va en la línea de log.
_BROADCAST = "async_broadcast"


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda la referencia al event loop principal de la app.

    Lo llama el `lifespan` de `create_app` en TODOS los roles (`http`,
    `sockets`, `all`): cualquier proceso que sirve peticiones tiene hilos de
    threadpool que necesitan saltar a su loop. En Celery o en el CLI nadie lo
    llama y `main_loop()` da `None`.
    """
    global _main_loop
    _main_loop = loop


def main_loop() -> asyncio.AbstractEventLoop | None:
    """El event loop principal registrado con `set_main_loop`, o `None`.

    Puede estar parado o cerrado (el apagado, o un loop de prueba que ya
    terminó): quien lo use desde otro hilo comprueba `is_running()`.
    """
    return _main_loop


def async_broadcast(coro) -> None:
    """
    Dispara un coroutine de broadcast de forma segura desde cualquier contexto
    (sync o async), sin esperar su resultado.

    - Si hay un event loop corriendo en el hilo actual → `spawn()` ahí.
    - Si no (hilo sync de FastAPI) → `spawn()` DENTRO del loop principal.
    - Sin loop principal corriendo → se descarta: la corrutina se cierra y se
      cuenta `status="dropped"`.

    `spawn()` y no `create_task`/`run_coroutine_threadsafe`: los dos dejaban
    la tarea sin referencia fuerte (el recolector podía destruirla a medio
    vuelo) y su excepción sin log ni contexto (ver `observability/spawn.py`).
    """
    # Caso 1: estamos en un contexto async (endpoint async, socket handler, etc.)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # Fuera del `try`: un error de `spawn` no debe caer al caso 2 con la
        # corrutina ya cerrada.
        spawn(coro, name=_BROADCAST)
        return

    # Caso 2: hilo sync (FastAPI def endpoints corriendo en threadpool).
    # `spawn_threadsafe` corre `spawn` en el hilo del loop principal, con el
    # contexto (el `request_id`) del hilo que llama. Si el loop se cerró entre
    # la comprobación y la programación (apagado) devuelve False y se descarta
    # como si no hubiera loop, sin lanzar al negocio.
    if spawn_threadsafe(coro, _main_loop, name=_BROADCAST):
        return

    discard(coro, name=_BROADCAST)
    logger.warning("async_broadcast: no hay event loop disponible, broadcast descartado")
