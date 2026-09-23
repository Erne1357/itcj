"""
Utilidades compartidas para itcj2 (FastAPI).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from functools import partial

from itcj2.observability.spawn import discard, spawn

logger = logging.getLogger(__name__)

# Referencia al event loop principal (se establece en lifespan/startup)
_main_loop: asyncio.AbstractEventLoop | None = None

# Sitio de `itcj_background_tasks_total` (R37): el mismo para los ~30
# llamadores, que no cambian. El evento concreto va en la línea de log.
_BROADCAST = "async_broadcast"


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda la referencia al event loop principal de la app."""
    global _main_loop
    _main_loop = loop


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
    # `call_soon_threadsafe` corre `spawn` en el hilo del loop: asyncio no es
    # thread-safe y la tarea y su done-callback deben nacer ahí. El contexto
    # del hilo que llama (el `request_id` de la petición, que anyio copió al
    # threadpool) se copia de forma EXPLÍCITA: la tarea y su log de error lo
    # heredan de ese callback. Una corrutina envoltorio también cruzaría el
    # contexto, pero sería una tarea más por broadcast y repetiría la cuenta
    # de `spawn`.
    loop = _main_loop
    if loop is not None and loop.is_running():
        try:
            loop.call_soon_threadsafe(
                partial(spawn, coro, name=_BROADCAST),
                context=contextvars.copy_context(),
            )
            return
        except RuntimeError:
            # El loop se cerró entre `is_running()` y aquí (apagado): se
            # descarta como si no hubiera loop, sin lanzar al negocio.
            pass

    discard(coro, name=_BROADCAST)
    logger.warning("async_broadcast: no hay event loop disponible, broadcast descartado")
