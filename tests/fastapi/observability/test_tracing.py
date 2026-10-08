"""Trazas OpenTelemetry (Fase 7): un solo trace id en todo el sistema.

Lo que se prueba es el contrato con Grafana: el `trace_id` de cada línea de
log en Loki (lo pone el filtro desde el contexto propio) tiene que existir en
Tempo como la traza del span que la emitió. Si no coinciden, el botón
Loki -> Tempo abre una traza vacía, en silencio.

El provider de prueba (`InMemorySpanExporter` + `SimpleSpanProcessor`) se
INYECTA en `setup_tracing(provider=...)`: así nunca se fija el provider
GLOBAL de OpenTelemetry (que solo se puede fijar una vez por proceso y
contaminaría el resto de la suite), y `shutdown_tracing()` deshace los
instrumentors al terminar cada test.

App de prueba igual que `test_middleware.py`: `setup_middleware()` real y los
handlers de error REALES de `itcj2/main.py`. La consulta a BD es un
`SELECT 1` por el `engine` real (el que instrumenta `setup_tracing`).
"""
import contextvars
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from itcj2.main import _register_error_handlers
from itcj2.middleware import setup_middleware
from itcj2.observability import context, tracing
from itcj2.observability.logging_config import ContextFilter, JsonFormatter
from itcj2.sockets.instrumentation import InstrumentedAsyncServer
from tests.conftest import TEST_SECRET
from tests.fastapi.observability._celery_helpers import (
    consume,
    memory_app,
    run_as_worker,
    unique_queue,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PREFIX = "/api/help-desk/v2/otel-probe"
ITEM_TEMPLATE = f"{PREFIX}/items/{{item_id}}"

_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
_PARENT_SPAN = "00f067aa0ba902b7"


class ProbeBoomError(Exception):
    pass


def _hex_trace(span) -> str:
    return format(span.context.trace_id, "032x")


def _hex_span(span) -> str:
    return format(span.context.span_id, "016x")


def _server_spans(exporter) -> list:
    return [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]


def _sql_spans(exporter) -> list:
    return [
        s for s in exporter.get_finished_spans()
        if "db.statement" in (s.attributes or {})
        or "db.query.text" in (s.attributes or {})
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def spans(monkeypatch):
    """Tracing ENCENDIDO con un provider de prueba; los spans terminados
    quedan en el exportador en memoria."""
    monkeypatch.setenv("OTEL_ENABLED", "1")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    assert tracing.setup_tracing(provider=provider) is provider
    try:
        yield exporter
    finally:
        tracing.shutdown_tracing()


@pytest.fixture()
def json_lines():
    """Líneas JSON de un logger de prueba con el filtro y el formato REALES
    de producción (lo que recoge Alloy del stdout)."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    probe_logger = logging.getLogger("tests.otel_probe")
    probe_logger.addHandler(handler)
    probe_logger.setLevel(logging.INFO)
    probe_logger.propagate = False
    try:
        yield lambda: [json.loads(line) for line in buffer.getvalue().splitlines()]
    finally:
        probe_logger.removeHandler(handler)


def _build_app() -> FastAPI:
    app = FastAPI()
    setup_middleware(app)
    _register_error_handlers(app)
    router = APIRouter(prefix="/items")

    @router.get("/{item_id}")
    def item(item_id: int):
        logging.getLogger("tests.otel_probe").info("dentro del endpoint")
        return {
            "trace_id": context.current_trace_id(),
            "span_id": context.current_span_id(),
        }

    @router.get("/{item_id}/db")
    def with_db(item_id: int):
        from sqlalchemy import text

        from itcj2.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"trace_id": context.current_trace_id()}

    @router.get("/{item_id}/unavailable")
    def unavailable(item_id: int):
        raise HTTPException(status_code=503, detail="mantenimiento")

    @router.get("/{item_id}/boom")
    def boom(item_id: int):
        raise ProbeBoomError("explota a propósito")

    app.include_router(router, prefix=PREFIX)
    return app


@pytest.fixture()
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        with TestClient(_build_app(), raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_una_peticion_produce_exactamente_un_span_servidor_con_la_plantilla(spans, client):
    response = client.get(f"{PREFIX}/items/4821")
    assert response.status_code == 200

    server = _server_spans(spans)
    assert len(server) == 1
    span = server[0]
    assert span.name == f"GET {ITEM_TEMPLATE}"
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == ITEM_TEMPLATE
    assert span.attributes["http.response.status_code"] == 200
    # Ruta matcheada: la cruda (con el id) no va a la traza, ya está la plantilla.
    assert "url.path" not in span.attributes
    assert span.status.status_code == StatusCode.UNSET


def test_un_404_se_llama_unmatched_y_lleva_la_ruta_cruda_sin_query(spans, client):
    response = client.get(f"{PREFIX}/no-existe?token=secreto")
    assert response.status_code == 404

    server = _server_spans(spans)
    assert len(server) == 1
    span = server[0]
    assert span.name == "GET __unmatched__"
    assert span.attributes["http.route"] == "__unmatched__"
    assert span.attributes["url.path"] == f"{PREFIX}/no-existe"
    assert all("secreto" not in str(v) for v in span.attributes.values())
    # Un 4xx es culpa del cliente: no marca la traza como error.
    assert span.status.status_code == StatusCode.UNSET


def test_current_trace_id_y_la_linea_json_son_los_del_span(spans, client, json_lines):
    body = client.get(f"{PREFIX}/items/7").json()

    (span,) = _server_spans(spans)
    assert body["trace_id"] == _hex_trace(span)
    assert body["span_id"] == _hex_span(span)

    (line,) = [l for l in json_lines() if l["msg"] == "dentro del endpoint"]
    assert line["trace_id"] == _hex_trace(span)
    assert line["span_id"] == _hex_span(span)


def test_la_consulta_a_bd_es_un_span_hijo_de_la_misma_traza(spans, client):
    body = client.get(f"{PREFIX}/items/7/db").json()

    (server,) = _server_spans(spans)
    sql = [s for s in _sql_spans(spans) if "SELECT 1" in str(s.attributes)]
    assert len(sql) == 1
    assert _hex_trace(sql[0]) == _hex_trace(server) == body["trace_id"]
    assert sql[0].parent is not None
    assert sql[0].parent.span_id == server.context.span_id


def test_traceparent_entrante_se_respeta(spans, client):
    body = client.get(
        f"{PREFIX}/items/7",
        headers={"traceparent": f"00-{_TRACE}-{_PARENT_SPAN}-01"},
    ).json()

    (span,) = _server_spans(spans)
    assert _hex_trace(span) == _TRACE
    assert format(span.parent.span_id, "016x") == _PARENT_SPAN
    assert body["trace_id"] == _TRACE
    # El span propio es nuevo, no el del llamante.
    assert body["span_id"] == _hex_span(span) != _PARENT_SPAN


def test_un_5xx_marca_el_span_como_error(spans, client):
    assert client.get(f"{PREFIX}/items/7/unavailable").status_code == 503

    (span,) = _server_spans(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 503


def test_una_excepcion_no_atrapada_marca_error_y_se_registra(spans, client):
    assert client.get(f"{PREFIX}/items/7/boom").status_code == 500

    (span,) = _server_spans(spans)
    assert span.name == f"GET {ITEM_TEMPLATE}/boom"
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 500
    events = [e for e in span.events if e.name == "exception"]
    assert len(events) == 1
    assert events[0].attributes["exception.type"].endswith("ProbeBoomError")


def test_setup_tracing_es_idempotente(spans, client):
    provider = tracing.setup_tracing()
    assert provider is not None
    # Una segunda llamada no reinstrumenta: una consulta, un span de SQL.
    assert tracing.setup_tracing() is provider

    client.get(f"{PREFIX}/items/7/db")
    assert len([s for s in _sql_spans(spans) if "SELECT 1" in str(s.attributes)]) == 1


def test_apagar_deshace_los_instrumentors(spans, client):
    provider = tracing.setup_tracing()
    # Sin cerrar el provider: el exportador sigue recibiendo, así que un
    # instrumentor que se quedara puesto SÍ dejaría spans aquí.
    with patch.object(provider, "shutdown"):
        tracing.shutdown_tracing()
    assert tracing.instrumented_libraries() == ()
    spans.clear()

    response = client.get(f"{PREFIX}/items/7/db")
    assert response.status_code == 200
    assert spans.get_finished_spans() == ()


def test_create_app_no_suma_la_telemetria_propia_de_fastapi(spans):
    # En producción `setup_tracing()` fija el provider GLOBAL, y FastAPI
    # (>= 0.142) enciende sola su telemetría en cuanto lo ve: un segundo span
    # servidor por fuera del middleware. Se simula ese global solo mientras
    # dura el test (sin `set_tracer_provider`, que es de una sola vez).
    from itcj2.main import create_app

    provider = tracing.setup_tracing()
    with patch.object(otel_trace, "_TRACER_PROVIDER", provider):
        with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
            app_client = TestClient(create_app(), raise_server_exceptions=False)
            assert app_client.get("/api/no-existe-otel").status_code == 404
            # /health está fuera del middleware: sin telemetría propia de
            # FastAPI no produce NINGÚN span.
            assert app_client.get("/health").status_code == 200

    finished = spans.get_finished_spans()
    assert [s.name for s in finished] == ["GET __unmatched__"]
    assert finished[0].parent is None


# ---------------------------------------------------------------------------
# Socket.IO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evento_de_socket_abre_un_span_raiz_con_el_trace_id_del_handler(spans):
    sio = InstrumentedAsyncServer(async_mode="asgi")
    seen = {}

    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        logging.getLogger("tests.otel_probe").info("handler")
        seen["trace_id"] = context.current_trace_id()
        seen["span_id"] = context.current_span_id()

    # Aunque el evento se despache con un span ajeno activo, el suyo es raíz.
    other = tracing.start_span("ajeno")
    try:
        await sio._trigger_event("ping", "/slots", "s1")
    finally:
        tracing.end_span(other)

    (span,) = [s for s in spans.get_finished_spans() if s.name.startswith("socketio")]
    assert span.name == "socketio /slots ping"
    assert span.parent is None
    assert seen == {"trace_id": _hex_trace(span), "span_id": _hex_span(span)}
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.asyncio
async def test_evento_de_socket_que_falla_marca_error(spans):
    sio = InstrumentedAsyncServer(async_mode="asgi")

    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        raise ProbeBoomError("socket")

    with pytest.raises(ProbeBoomError):
        await sio._trigger_event("ping", "/slots", "s1")

    (span,) = [s for s in spans.get_finished_spans() if s.name.startswith("socketio")]
    assert span.status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_evento_sin_handler_no_pone_el_nombre_del_cliente_en_el_span(spans):
    sio = InstrumentedAsyncServer(async_mode="asgi")

    await sio._trigger_event("inventado-por-el-cliente", "/slots", "s1")

    (span,) = [s for s in spans.get_finished_spans() if s.name.startswith("socketio")]
    assert span.name == "socketio /slots otro"


# ---------------------------------------------------------------------------
# Celery (prefork: setup_tracing va en worker_process_init, aquí directo)
# ---------------------------------------------------------------------------

celery = memory_app("itcj-obs-tracing")
_task_seen: list[dict] = []


@celery.task(name="tests.observability.tracing.probe", shared=False)
def celery_probe():
    _task_seen.append({
        "trace_id": context.current_trace_id(),
        "span_id": context.current_span_id(),
        "snapshot_trace_id": context.snapshot()["trace_id"],
    })


def _run_task(publish_bound: bool):
    """Publica (con o sin una petición activa) y ejecuta como el worker, cada
    lado en su propio contexto: son procesos distintos en producción."""
    _task_seen.clear()
    queue = unique_queue()

    def _publish():
        active = None
        if publish_bound:
            active = tracing.start_span("GET /petición")
            context.bind(trace_id=active.trace_id, span_id=active.span_id)
        try:
            celery_probe.apply_async(queue=queue)
        finally:
            if active is not None:
                tracing.end_span(active)
        return active

    publisher = contextvars.Context().run(_publish)
    message = consume(celery, queue)
    contextvars.Context().run(run_as_worker, celery, message)
    (seen,) = _task_seen
    return publisher, seen


def _run_span(exporter):
    (span,) = [
        s for s in exporter.get_finished_spans()
        if s.kind == SpanKind.CONSUMER
    ]
    return span


def test_tarea_celery_ve_el_trace_id_del_span_de_celery_instrumentor(spans):
    publisher, seen = _run_task(publish_bound=True)

    run = _run_span(spans)
    assert _hex_trace(run) == publisher.trace_id
    assert seen["trace_id"] == publisher.trace_id
    assert seen["snapshot_trace_id"] == publisher.trace_id
    assert seen["span_id"] == _hex_span(run)


def test_tarea_sin_peticion_detras_liga_la_raiz_del_span_de_celery(spans):
    # Beat / CLI: no hay traza que heredar; la raíz la abre CeleryInstrumentor
    # y el contexto propio tiene que ligar ESA, no acuñar una distinta.
    _, seen = _run_task(publish_bound=False)

    run = _run_span(spans)
    assert seen["trace_id"] == _hex_trace(run)
    assert seen["snapshot_trace_id"] == _hex_trace(run)
    assert seen["span_id"] == _hex_span(run)


# ---------------------------------------------------------------------------
# Apagado (OTEL_ENABLED != "1"): idéntico a hoy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "0", "", "true"])
def test_apagado_no_instala_provider_y_los_ids_salen_como_hoy(monkeypatch, client, value):
    if value is None:
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
    else:
        monkeypatch.setenv("OTEL_ENABLED", value)

    assert tracing.setup_tracing() is None
    assert tracing.start_span("x") is None
    assert not isinstance(otel_trace.get_tracer_provider(), TracerProvider)

    body = client.get(f"{PREFIX}/items/7").json()
    assert len(body["trace_id"]) == 32 and len(body["span_id"]) == 16

    tracing.shutdown_tracing()  # sin nada instalado, no lanza


def test_en_un_proceso_nuevo_se_instrumentan_las_cinco_bibliotecas():
    # Proceso nuevo, como un worker de uvicorn o un hijo del prefork: un
    # instrumentor que falla al importar (pasó con SQLAlchemy 2.1 sin
    # greenlet) solo deja un ERROR en el log; dentro de la suite lo taparía
    # un import que otro test ya intentó.
    code = """
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text
from itcj2.observability import tracing
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
tracing.setup_tracing(provider=provider)
print(sorted(tracing.instrumented_libraries()))
from itcj2.database import engine
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
print(any("SELECT 1" in str(s.attributes) for s in exporter.get_finished_spans()))
"""
    env = {**os.environ, "OTEL_ENABLED": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "no se pudo instrumentar" not in result.stderr + result.stdout
    assert result.stdout.splitlines()[-2:] == [
        "['celery', 'httpx', 'redis', 'requests', 'sqlalchemy']",
        "True",
    ]


def test_apagado_ni_siquiera_importa_el_sdk():
    code = (
        "import sys\n"
        "from itcj2.observability import tracing\n"
        "assert tracing.setup_tracing() is None\n"
        "assert not any(m.startswith('opentelemetry.sdk') for m in sys.modules), "
        "sorted(m for m in sys.modules if m.startswith('opentelemetry'))\n"
    )
    env = {**os.environ, "OTEL_ENABLED": "0"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Provider de producción
# ---------------------------------------------------------------------------

def test_el_provider_de_produccion_lleva_el_recurso_y_el_endpoint(monkeypatch):
    monkeypatch.setenv("INSTANCE_COLOR", "green")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    provider = tracing.build_provider(role="http")
    try:
        attrs = provider.resource.attributes
        assert attrs["service.name"] == "itcj"
        assert attrs["service.namespace"] == "green"
        assert attrs["deployment.environment"] == "prod"
        assert attrs["itcj.app_role"] == "http"
        assert provider.sampler.get_description() == "AlwaysOnSampler"
        assert tracing.otlp_endpoint() == "http://alloy:4317"
    finally:
        provider.shutdown()


def test_el_endpoint_sale_del_entorno(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otro:4317")
    assert tracing.otlp_endpoint() == "http://otro:4317"
