"""
Utilidades compartidas para itcj2 (FastAPI).
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Referencia al event loop principal (se establece en lifespan/startup)
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda la referencia al event loop principal de la app."""
    global _main_loop
    _main_loop = loop


def async_broadcast(coro) -> None:
    """
    Dispara un coroutine de broadcast de forma segura desde cualquier contexto
    (sync o async).

    - Si hay un event loop corriendo en el hilo actual → create_task.
    - Si no (hilo sync de FastAPI) → run_coroutine_threadsafe en el loop principal.
    """
    # Caso 1: estamos en un contexto async (endpoint async, socket handler, etc.)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
        return
    except RuntimeError:
        pass

    # Caso 2: hilo sync (FastAPI def endpoints corriendo en threadpool)
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    else:
        logger.warning("async_broadcast: no hay event loop disponible, broadcast descartado")
