"""Métricas RED que registra `ObservabilityMiddleware` (plan Fase 2, test 2).

Los contadores de `itcj2.observability.metrics` son de MÓDULO: viven lo que
vive el proceso de pytest y acumulan entre tests (y entre archivos: otros
tests también pasan por el middleware). Por eso todo se mide como DELTA con
`REGISTRY.get_sample_value`, nunca como valor absoluto.

`get_sample_value` exige el juego de etiquetas EXACTO: si una métrica llevara
una etiqueta de más (p. ej. `status` en el histograma) la consulta devolvería
`None` y el delta no cuadraría. Eso ya fija el contrato de etiquetas.

Sin BD ni datos sembrados: la app de prueba solo tiene rutas propias.
"""
import asyncio
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from itcj2.main import _register_error_handlers
from itcj2.middleware import setup_middleware
from itcj2.observability.middleware import ObservabilityMiddleware
from tests.conftest import TEST_SECRET

# Prefijo real de helpdesk: `app` sale de la plantilla ("helpdesk").
PREFIX = "/api/help-desk/v2/red-probe"
ITEM_TEMPLATE = f"{PREFIX}/items/{{item_id}}"

REQUESTS = "itcj_http_requests_total"
DURATION_COUNT = "itcj_http_request_duration_seconds_count"
IN_FLIGHT = "itcj_http_requests_in_flight"
EXCEPTIONS = "itcj_http_exceptions_total"


class RedProbeError(Exception):
    """Nombre propio: prueba que `exc_type` es el tipo REAL de la excepción."""


def _value(name: str, labels: dict) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _family_total(sample_name: str) -> float:
    """Suma de TODAS las series de una muestra, sea cual sea su etiqueta."""
    total = 0.0
    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name == sample_name:
                total += sample.value
    return total


def _build_app() -> FastAPI:
    app = FastAPI()
    setup_middleware(app)
    _register_error_handlers(app)

    router = APIRouter(prefix="/items")

    @router.get("/{item_id}")
    def item(item_id: int):
        return {"item_id": item_id}

    @router.get("/{item_id}/in-flight")
    def in_flight(item_id: int):
        # Leído DENTRO de la petición: el middleware ya tuvo que sumarla.
        return {"in_flight": _value(IN_FLIGHT, {"app": "helpdesk"})}

    @router.get("/{item_id}/unavailable")
    def unavailable(item_id: int):
        raise HTTPException(status_code=503, detail="mantenimiento")

    @router.get("/{item_id}/boom")
    def boom(item_id: int):
        raise RedProbeError("explota a propósito")

    app.include_router(router, prefix=PREFIX)

    def excluded():
        return {"ok": True}

    for path in ("/health", "/ready", "/metrics"):
        app.add_api_route(path, excluded, methods=["GET"])

    return app


@pytest.fixture()
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        # raise_server_exceptions=False: el 500 de la excepción no controlada
        # lo manda ServerErrorMiddleware y luego re-lanza; sin esto el
        # TestClient la re-lanzaría en el test.
        with TestClient(_build_app(), raise_server_exceptions=False) as c:
            yield c


def _requests_labels(route: str, status: str, app: str = "helpdesk") -> dict:
    return {"app": app, "method": "GET", "route": route, "status": status}


# ---------------------------------------------------------------------------
# Contador de peticiones
# ---------------------------------------------------------------------------

def test_route_with_param_is_counted_with_its_template(client):
    labels = _requests_labels(ITEM_TEMPLATE, "200")
    before = _value(REQUESTS, labels)
    raw_before = _value(REQUESTS, _requests_labels(f"{PREFIX}/items/7", "200"))

    resp = client.get(f"{PREFIX}/items/7")

    assert resp.status_code == 200
    assert _value(REQUESTS, labels) - before == 1
    # Nunca la ruta cruda: cada id sería una serie nueva.
    assert _value(REQUESTS, _requests_labels(f"{PREFIX}/items/7", "200")) == raw_before


def test_404_is_counted_as_unmatched_under_otro(client):
    labels = _requests_labels("__unmatched__", "404", app="otro")
    before = _value(REQUESTS, labels)

    resp = client.get(f"{PREFIX}/no-existe/48213")

    assert resp.status_code == 404
    assert _value(REQUESTS, labels) - before == 1


def test_http_exception_keeps_its_status(client):
    # La convierte ExceptionMiddleware POR DENTRO del middleware: llega por el
    # send envuelto con su 503 y no es una excepción no controlada.
    labels = _requests_labels(f"{ITEM_TEMPLATE}/unavailable", "503")
    before = _value(REQUESTS, labels)
    exceptions_before = _family_total(EXCEPTIONS)

    resp = client.get(f"{PREFIX}/items/7/unavailable")

    assert resp.status_code == 503
    assert _value(REQUESTS, labels) - before == 1
    assert _family_total(EXCEPTIONS) == exceptions_before


def test_unhandled_exception_counts_500_and_its_type(client):
    route = f"{ITEM_TEMPLATE}/boom"
    labels = _requests_labels(route, "500")
    exc_labels = {"app": "helpdesk", "route": route, "exc_type": "RedProbeError"}
    before = _value(REQUESTS, labels)
    exc_before = _value(EXCEPTIONS, exc_labels)

    resp = client.get(f"{PREFIX}/items/7/boom")

    # El 500 lo emite ServerErrorMiddleware por FUERA del send envuelto
    # (plan §9.15): solo el `except BaseException` del middleware lo ve.
    assert resp.status_code == 500
    assert _value(REQUESTS, labels) - before == 1
    assert _value(EXCEPTIONS, exc_labels) - exc_before == 1


@pytest.mark.parametrize("path", ["/ready", "/health", "/metrics"])
def test_excluded_paths_record_nothing(client, path):
    totals_before = [
        _family_total(name) for name in (REQUESTS, DURATION_COUNT, EXCEPTIONS)
    ]

    resp = client.get(path)

    assert resp.status_code == 200
    totals_after = [
        _family_total(name) for name in (REQUESTS, DURATION_COUNT, EXCEPTIONS)
    ]
    assert totals_after == totals_before


# ---------------------------------------------------------------------------
# In-flight e histograma
# ---------------------------------------------------------------------------

def test_in_flight_is_up_during_the_request_and_back_after(client):
    labels = {"app": "helpdesk"}
    before = _value(IN_FLIGHT, labels)

    resp = client.get(f"{PREFIX}/items/7/in-flight")

    assert resp.json()["in_flight"] == before + 1
    assert _value(IN_FLIGHT, labels) == before


def test_in_flight_is_back_after_an_unhandled_exception(client):
    labels = {"app": "helpdesk"}
    before = _value(IN_FLIGHT, labels)

    client.get(f"{PREFIX}/items/7/boom")

    assert _value(IN_FLIGHT, labels) == before


def test_histogram_has_no_status_label(client):
    labels = {"app": "helpdesk", "method": "GET", "route": ITEM_TEMPLATE}
    before = _value(DURATION_COUNT, labels)

    client.get(f"{PREFIX}/items/7")

    # Etiquetas EXACTAS app/method/route: con `status` esto sería None.
    assert _value(DURATION_COUNT, labels) - before == 1
    [family] = [
        f for f in REGISTRY.collect()
        if f.name == "itcj_http_request_duration_seconds"
    ]
    assert family.samples
    for sample in family.samples:
        assert "status" not in sample.labels, sample


# ---------------------------------------------------------------------------
# R19: la app termina sin responder y sin lanzar
# ---------------------------------------------------------------------------

def _http_scope(path: str) -> dict:
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


def test_app_returning_without_response_counts_as_500():
    # Uvicorn responde entonces con su propio 500 ("ASGI callable returned
    # without starting response"): eso es lo que vio el cliente.
    async def silent(scope, receive, send):
        return None

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    labels = _requests_labels("__unmatched__", "500", app="otro")
    before = _value(REQUESTS, labels)
    exceptions_before = _family_total(EXCEPTIONS)

    asyncio.run(ObservabilityMiddleware(silent)(_http_scope("/x/1"), receive, send))

    assert _value(REQUESTS, labels) - before == 1
    # Sin excepción no hay `exc_type` que contar.
    assert _family_total(EXCEPTIONS) == exceptions_before
