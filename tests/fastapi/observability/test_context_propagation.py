"""La matriz de propagación de contexto (plan §3.0) convertida en test.

Que HOY el `request_id` llegue a un hilo del threadpool o a una corrutina
programada con `run_coroutine_threadsafe` no es un contrato de nadie: depende
de que anyio corra el endpoint `def` dentro de un contexto copiado y de que
`call_soon_threadsafe` copie el contexto del hilo que llama — dos detalles de
implementación, ninguno documentado. Un `pip install -U starlette` o `anyio`
puede romperlo en silencio y los ids simplemente saldrían vacíos en los logs.
Este módulo es el que se pone rojo cuando eso pase.

La app de prueba monta el `JWTMiddleware` REAL con `setup_middleware()` (así
el `ObservabilityMiddleware` queda por fuera, igual que en producción) y cada
endpoint devuelve el `current_request_id()` que ve desde su frontera; el
test lo compara con el `X-Request-ID` de la respuesta. El salto a Celery
(Fase 5a) se prueba igual, pero el cuerpo de la tarea corre DESPUÉS de la
respuesta, desde el mensaje que el endpoint dejó en el broker.

Sin BD ni datos sembrados: las peticiones son anónimas (el JWT no consulta
nada sin cookie).
"""
import asyncio
import contextvars
import re
import threading
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

import itcj2.utils
from itcj2.middleware import setup_middleware
from itcj2.observability.context import current_request_id
from itcj2.utils import async_broadcast, set_main_loop
from tests.fastapi.observability._celery_helpers import (
    consume,
    memory_app,
    run_as_worker,
    unique_queue,
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")

# (g) Broker `memory://`, no eager: en eager Celery no dispara
# `before_task_publish` y el test no pasaría por la publicación.
_celery = memory_app("itcj-obs-propagation")
_celery_seen: list[str] = []


@_celery.task(name="tests.observability.propagation.probe_request_id")
def _probe_request_id():
    _celery_seen.append(current_request_id())


def _build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        # Lo mismo que hace el lifespan real de itcj2/main.py: sin el loop
        # principal registrado, `async_broadcast` desde un endpoint `def`
        # descarta la corrutina y el caso (f) no probaría nada.
        set_main_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(lifespan=lifespan)
    setup_middleware(app)

    # (a) endpoint async: misma Task que el middleware.
    @app.get("/probe/async")
    async def probe_async():
        return {"request_id": current_request_id()}

    # (b) endpoint def: corre en el threadpool de anyio.
    @app.get("/probe/sync")
    def probe_sync():
        return {"request_id": current_request_id()}

    # (c) asyncio.to_thread desde un endpoint async.
    @app.get("/probe/to-thread")
    async def probe_to_thread():
        return {"request_id": await asyncio.to_thread(current_request_id)}

    # (d) run_in_threadpool de starlette.
    @app.get("/probe/threadpool")
    async def probe_threadpool():
        return {"request_id": await run_in_threadpool(current_request_id)}

    # (e) corrutina lanzada con loop.create_task y esperada.
    @app.get("/probe/create-task")
    async def probe_create_task():
        async def read():
            return current_request_id()

        task = asyncio.get_running_loop().create_task(read())
        return {"request_id": await task}

    # (f) corrutina pasada a async_broadcast desde un endpoint def: sin loop
    # en el hilo del threadpool, cae a run_coroutine_threadsafe sobre el loop
    # principal — el camino que usan los broadcasts reales de Socket.IO.
    @app.get("/probe/broadcast")
    def probe_broadcast():
        seen = {}
        done = threading.Event()
        endpoint_thread = threading.get_ident()

        async def read():
            seen["request_id"] = current_request_id()
            seen["other_thread"] = threading.get_ident() != endpoint_thread
            done.set()

        async_broadcast(read())
        return {"ran": done.wait(5), **seen}

    # (g) endpoint def que encola una tarea Celery, como los sitios reales.
    @app.get("/probe/celery")
    def probe_celery(queue: str):
        _probe_request_id.apply_async(queue=queue)
        return {"queued": True}

    return app


@pytest.fixture()
def client(monkeypatch):
    # El lifespan fija el loop global de itcj2.utils; se restaura al salir
    # para no dejarle a otro test un loop ya cerrado.
    monkeypatch.setattr(itcj2.utils, "_main_loop", None)
    with TestClient(_build_app()) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/probe/async",
        "/probe/sync",
        "/probe/to-thread",
        "/probe/threadpool",
        "/probe/create-task",
    ],
)
def test_request_id_propagates_and_matches_response_header(client, path):
    resp = client.get(path)

    assert resp.status_code == 200
    header = resp.headers.get("x-request-id", "")
    assert _HEX32.match(header), f"X-Request-ID ausente o mal formado: {header!r}"
    assert resp.json()["request_id"] == header


def test_request_id_propagates_through_async_broadcast_from_sync_endpoint(client):
    resp = client.get("/probe/broadcast")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ran"], "async_broadcast no ejecutó la corrutina en el loop principal"
    # Si corriera en el mismo hilo del endpoint, no se estaría probando el
    # camino run_coroutine_threadsafe sino otro.
    assert body["other_thread"]
    header = resp.headers.get("x-request-id", "")
    assert _HEX32.match(header)
    assert body["request_id"] == header


def test_request_id_reaches_the_celery_task_it_enqueues(client):
    # Antes de la Fase 5a esto era un negativo (`.apply()` fuera de petición,
    # id vacío). Invertir aquel assert no probaba nada: `.apply()` nunca pasa
    # por la publicación. Aquí el endpoint publica de verdad y el cuerpo corre
    # como en el worker: en otro contexto, después de la respuesta, con el id
    # llegado en la cabecera del mensaje.
    _celery_seen.clear()
    queue = unique_queue()

    resp = client.get("/probe/celery", params={"queue": queue})

    assert resp.status_code == 200
    header = resp.headers.get("x-request-id", "")
    assert _HEX32.match(header)
    contextvars.Context().run(run_as_worker, _celery, consume(_celery, queue))
    assert _celery_seen == [header]


# ---------------------------------------------------------------------------
# Negativos: fronteras que HOY no llevan contexto
# ---------------------------------------------------------------------------

def test_socketio_handler_outside_request_has_no_request_id():
    # NEGATIVO HOY — SE INVIERTE EN LA FASE 5c: cada evento de Socket.IO
    # tendrá ids propios. Hoy un handler no tiene petición HTTP de la que
    # heredar. Se registra en el servidor REAL (en un namespace de prueba que
    # se retira al final) y se dispara por la misma vía interna que usa
    # python-socketio para llamar a los handlers.
    from itcj2.sockets.server import sio

    namespace = "/obs-probe"
    seen = {}

    async def on_probe(sid, data):
        seen["request_id"] = current_request_id()

    sio.on("probe", handler=on_probe, namespace=namespace)
    try:
        asyncio.run(sio._trigger_event("probe", namespace, "sid-probe", {}))
    finally:
        sio.handlers.pop(namespace, None)

    assert seen == {"request_id": ""}
