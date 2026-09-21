"""Tests de `itcj2.observability.middleware.ObservabilityMiddleware`.

Dos niveles:
- Integración: una app FastAPI de prueba con `setup_middleware()` (JWT real,
  CORS y el middleware de observabilidad por fuera) y los handlers de error
  REALES de `itcj2/main.py`, para que el 500 de una excepción no controlada
  sea exactamente el que ve producción.
- ASGI crudo: el middleware envolviendo una app mínima, para lo que un
  `TestClient` no deja observar (scopes `lifespan`/`websocket`, mensajes de
  cuerpo uno por uno, el contexto después de que la petición terminó).

Sin BD ni datos sembrados: el JWT se firma con el secreto de prueba y la
petición autenticada no dispara el refresh (le quedan 12 h).
"""
import asyncio
import logging
import re
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from itcj2.main import _register_error_handlers
from itcj2.middleware import setup_middleware
from itcj2.observability import context
from itcj2.observability.middleware import ObservabilityMiddleware
from tests.conftest import TEST_SECRET, make_jwt

ACCESS_LOGGER = "itcj2.access"
# Prefijo real de helpdesk: prueba de paso que `app` sale de la plantilla.
PREFIX = "/api/help-desk/v2/obs-probe"

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")

_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
_PARENT_SPAN = "00f067aa0ba902b7"


class ProbeBoomError(Exception):
    """Excepción propia: su nombre en `exc_type` prueba que se registra el
    tipo REAL y no uno genérico."""


def _build_app(seen: dict) -> FastAPI:
    app = FastAPI()
    setup_middleware(app)
    _register_error_handlers(app)

    # Router con prefijo propio incluido bajo otro prefijo: la línea-resumen
    # tiene que traer la plantilla COMPLETA, no el tramo del router hoja
    # (`/items/{item_id}`), que es lo que dejaría `scope["route"].path`.
    router = APIRouter(prefix="/items")

    @router.get("/{item_id}")
    def item(item_id: int):
        return {
            "trace_id": context.current_trace_id(),
            "span_id": context.current_span_id(),
            "request_id": context.current_request_id(),
        }

    @router.get("/{item_id}/unavailable")
    def unavailable(item_id: int):
        raise HTTPException(status_code=503, detail="mantenimiento")

    @router.get("/{item_id}/boom")
    def boom(item_id: int):
        seen["request_id"] = context.current_request_id()
        raise ProbeBoomError("explota a propósito")

    @router.get("/{item_id}/stream")
    def stream(item_id: int):
        def chunks():
            yield b"uno-"
            yield b"dos-"
            yield b"tres"

        return StreamingResponse(chunks(), media_type="text/plain")

    app.include_router(router, prefix=PREFIX)

    def excluded():
        return {"ok": True}

    for path in ("/health", "/ready", "/metrics"):
        app.add_api_route(path, excluded, methods=["GET"])

    return app


@pytest.fixture()
def seen() -> dict:
    return {}


@pytest.fixture()
def client(seen):
    # `_decode_jwt` lee `_JWT_SECRET` del módulo en cada llamada: basta el
    # patch mientras viva el cliente.
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        # raise_server_exceptions=False: ServerErrorMiddleware re-lanza SIEMPRE
        # después de mandar el 500; sin esto el TestClient la re-lanzaría en
        # el test en vez de devolver la respuesta.
        with TestClient(_build_app(seen), raise_server_exceptions=False) as c:
            yield c


def _access_records(caplog) -> list:
    return [r for r in caplog.records if r.name == ACCESS_LOGGER]


class _ContextProbe(logging.Handler):
    """Anota el `request_id` del contexto EN EL MOMENTO de emitir cada
    registro — lo que verá el filtro de logs (Task 4) sobre ese registro."""

    def __init__(self):
        super().__init__()
        self.seen = []

    def emit(self, record):
        self.seen.append((record.getMessage(), context.current_request_id()))


# ---------------------------------------------------------------------------
# X-Request-ID
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, expected_status",
    [
        (f"{PREFIX}/items/7", 200),
        (f"{PREFIX}/no-existe", 404),
        (f"{PREFIX}/items/7/unavailable", 503),
    ],
)
def test_x_request_id_on_every_wrapped_response(client, path, expected_status):
    resp = client.get(path)

    assert resp.status_code == expected_status
    header = resp.headers.get("x-request-id", "")
    assert _HEX32.match(header), f"X-Request-ID ausente o mal formado: {header!r}"


def test_x_request_id_is_the_bound_request_id(client):
    resp = client.get(f"{PREFIX}/items/7")

    assert resp.json()["request_id"] == resp.headers["x-request-id"]


def test_two_requests_get_distinct_request_ids(client):
    first = client.get(f"{PREFIX}/items/1").headers["x-request-id"]
    second = client.get(f"{PREFIX}/items/1").headers["x-request-id"]

    assert first != second


def test_incoming_x_request_id_is_not_honored(client):
    # El request_id lo genera SIEMPRE el servidor: un id elegido por el
    # cliente podría colisionar a propósito con el de otra petición.
    resp = client.get(f"{PREFIX}/items/1", headers={"X-Request-ID": "a" * 32})

    assert resp.headers["x-request-id"] != "a" * 32
    assert resp.json()["request_id"] == resp.headers["x-request-id"]


# ---------------------------------------------------------------------------
# traceparent entrante
# ---------------------------------------------------------------------------

def test_valid_traceparent_binds_its_trace_id(client):
    resp = client.get(
        f"{PREFIX}/items/1",
        headers={"traceparent": f"00-{_TRACE}-{_PARENT_SPAN}-01"},
    )

    body = resp.json()
    assert body["trace_id"] == _TRACE
    # El span del traceparent es el del LLAMANTE (padre); esta petición abre
    # uno propio.
    assert _HEX16.match(body["span_id"])
    assert body["span_id"] != _PARENT_SPAN


@pytest.mark.parametrize(
    "value",
    [
        "basura",
        f"00-{'0' * 32}-{_PARENT_SPAN}-01",       # trace_id todo ceros
        f"00-{_TRACE.upper()}-{_PARENT_SPAN}-01",  # W3C exige minúsculas
        f"01-{_TRACE}-{_PARENT_SPAN}-01",          # versión desconocida
    ],
)
def test_invalid_traceparent_is_ignored(client, value):
    resp = client.get(f"{PREFIX}/items/1", headers={"traceparent": value})

    trace_id = resp.json()["trace_id"]
    assert _HEX32.match(trace_id)
    assert trace_id not in (_TRACE, "0" * 32)


# ---------------------------------------------------------------------------
# Línea-resumen por petición
# ---------------------------------------------------------------------------

def test_summary_line_for_a_normal_request(client, caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        resp = client.get(f"{PREFIX}/items/7")

    [record] = _access_records(caplog)
    assert record.levelno == logging.INFO
    assert record.method == "GET"
    assert record.route == f"{PREFIX}/items/{{item_id}}"
    assert record.app == "helpdesk"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0
    assert record.user_id == ""
    assert not hasattr(record, "exc_type")
    assert re.fullmatch(
        rf"GET {re.escape(PREFIX)}/items/\{{item_id\}} 200 \d+\.\dms",
        record.getMessage(),
    ), record.getMessage()
    assert resp.status_code == 200


def test_summary_line_for_unmatched_route(client, caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        client.get(f"{PREFIX}/no-existe/4821")

    [record] = _access_records(caplog)
    # Nunca la ruta cruda: cada URL inventada por un escáner sería una serie.
    assert record.route == "__unmatched__"
    assert record.app == "otro"
    assert record.status == 404


def test_summary_line_carries_user_id_from_jwt(client, caplog):
    token = make_jwt(user_id=200)

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        client.get(f"{PREFIX}/items/7", headers={"Cookie": f"itcj_token={token}"})

    [record] = _access_records(caplog)
    assert record.user_id == "200"


def test_summary_line_for_http_exception_keeps_its_status(client, caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        client.get(f"{PREFIX}/items/7/unavailable")

    [record] = _access_records(caplog)
    assert record.status == 503
    # Una HTTPException la convierte ExceptionMiddleware POR DENTRO: no es
    # una excepción no controlada.
    assert not hasattr(record, "exc_type")


@pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
def test_excluded_paths_are_not_instrumented(client, caplog, path):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        resp = client.get(path)

    assert resp.status_code == 200
    assert _access_records(caplog) == []
    assert "x-request-id" not in resp.headers


# ---------------------------------------------------------------------------
# Excepción no controlada (plan §9.15, ruling R4)
# ---------------------------------------------------------------------------

def test_unhandled_exception_is_logged_as_500_and_reaches_global_handler(
    client, caplog, seen
):
    probe = _ContextProbe()
    itcj2_logger = logging.getLogger("itcj2")
    itcj2_logger.addHandler(probe)
    try:
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
            resp = client.get(f"{PREFIX}/items/5/boom")
    finally:
        itcj2_logger.removeHandler(probe)

    # La excepción siguió subiendo hasta el handler global de itcj2/main.py.
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error", "status": 500}
    # Ese 500 lo emite ServerErrorMiddleware, POR FUERA del send envuelto.
    assert "x-request-id" not in resp.headers

    [record] = _access_records(caplog)
    assert record.status == 500
    assert record.exc_type == "ProbeBoomError"
    assert record.route == f"{PREFIX}/items/{{item_id}}/boom"

    # R4: el logger.exception del handler global corre por fuera del
    # middleware y todavía ve el request_id de la petición que falló.
    request_id = seen["request_id"]
    assert _HEX32.match(request_id)
    unhandled = [rid for msg, rid in probe.seen if msg.startswith("Unhandled exception")]
    assert unhandled == [request_id]


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def test_streaming_response_passes_with_header(client, caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        resp = client.get(f"{PREFIX}/items/1/stream")

    assert resp.status_code == 200
    assert resp.content == b"uno-dos-tres"
    assert resp.headers["content-type"].startswith("text/plain")
    assert _HEX32.match(resp.headers["x-request-id"])
    [record] = _access_records(caplog)
    assert record.status == 200


# ---------------------------------------------------------------------------
# ASGI crudo
# ---------------------------------------------------------------------------

def _http_scope(path="/api/x") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 80),
    }


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def test_streaming_chunks_pass_one_by_one():
    # Cada mensaje de cuerpo sale tal cual y en su orden: el middleware no
    # junta el stream (un export de Excel no se materializa en memoria).
    async def chunks():
        for part in (b"uno-", b"dos-", b"tres"):
            yield part

    middleware = ObservabilityMiddleware(
        StreamingResponse(chunks(), media_type="text/plain")
    )
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(_http_scope(), _receive, send))

    start, *bodies = sent
    assert start["type"] == "http.response.start"
    names = [name for name, _ in start["headers"]]
    assert b"content-type" in names
    assert names.count(b"x-request-id") == 1
    assert [m["body"] for m in bodies if m["body"]] == [b"uno-", b"dos-", b"tres"]
    assert bodies[-1]["more_body"] is False


@pytest.mark.parametrize(
    "scope",
    [
        {"type": "lifespan"},
        {"type": "websocket", "path": "/ws", "headers": []},
    ],
    ids=["lifespan", "websocket"],
)
def test_non_http_scopes_pass_untouched(scope, caplog):
    before = dict(scope)
    calls = {}

    async def inner(s, r, snd):
        calls.update(
            scope=s, receive=r, send=snd, request_id=context.current_request_id()
        )

    async def send(message):
        pass

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        asyncio.run(ObservabilityMiddleware(inner)(scope, _receive, send))

    assert calls["scope"] is scope and scope == before
    assert calls["receive"] is _receive
    assert calls["send"] is send
    assert calls["request_id"] == ""
    assert _access_records(caplog) == []


def test_context_is_reset_after_a_request_without_exception():
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        pass

    async def main():
        await ObservabilityMiddleware(inner)(_http_scope(), _receive, send)
        return context.current_request_id(), context.current_scope()

    assert asyncio.run(main()) == ("", None)


def test_app_returning_without_response_is_logged_as_500(caplog):
    # R19: la app termina sin http.response.start y sin lanzar. Uvicorn
    # responde entonces con su propio 500 ("ASGI callable returned without
    # starting response"): eso es lo que vio el cliente, no un status vacío.
    async def silent(scope, receive, send):
        return None

    async def send(message):
        pass

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        asyncio.run(ObservabilityMiddleware(silent)(_http_scope(), _receive, send))

    [record] = _access_records(caplog)
    assert record.status == 500
    assert not hasattr(record, "exc_type")


def test_response_start_without_headers_key_gets_the_request_id():
    # R20: ASGI permite omitir "headers" en http.response.start.
    async def bare(scope, receive, send):
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(ObservabilityMiddleware(bare)(_http_scope(), _receive, send))

    start = sent[0]
    assert start["status"] == 204
    [(name, value)] = start["headers"]
    assert name == b"x-request-id"
    assert _HEX32.match(value.decode())
