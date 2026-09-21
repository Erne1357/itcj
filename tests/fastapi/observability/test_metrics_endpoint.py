"""`GET /metrics` de la app REAL (plan Fase 2, test 1).

`TestClient` sin `with`: no corre el lifespan (ni el subscriber de Redis ni
el `engine.dispose()` del apagado), que aquí no aporta nada. Sin datos
sembrados: la única ruta de negocio que se pide va sin cookie y responde
401/403.

Sin `PROMETHEUS_MULTIPROC_DIR` (pytest no lo pone): `render_latest()` sirve el
registro plano del proceso. El camino multiproceso se prueba en subprocesos
en `test_reaper.py`.
"""
import pytest
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.parser import text_string_to_metric_families

from itcj2.main import create_app
from itcj2.observability import metrics

TICKET_PATH = "/api/help-desk/v2/tickets/4821"
TICKET_TEMPLATE = "/api/help-desk/v2/tickets/{ticket_id}"


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


def _ticket_requests(body: str) -> float:
    """Suma de `itcj_http_requests_total` de la ruta plantillada del ticket
    (sea cual sea el status: sin cookie es 401 o 403 según el dependency)."""
    total = 0.0
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if (
                sample.name == "itcj_http_requests_total"
                and sample.labels.get("route") == TICKET_TEMPLATE
            ):
                total += sample.value
    return total


def test_metrics_responds_200_with_prometheus_content_type(client):
    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == CONTENT_TYPE_LATEST


def test_metrics_carries_requests_with_the_templated_route(client):
    before = _ticket_requests(client.get("/metrics").text)

    for _ in range(3):
        assert client.get(TICKET_PATH).status_code in (401, 403)

    body = client.get("/metrics").text
    assert _ticket_requests(body) - before == 3
    # La ruta cruda (con el id) nunca llega a una etiqueta.
    assert f'route="{TICKET_PATH}"' not in body


def test_metrics_does_not_measure_itself(client):
    client.get("/metrics")
    body = client.get("/metrics").text

    assert 'route="/metrics"' not in body


def test_metrics_is_not_in_the_openapi_schema(app):
    assert "/metrics" not in app.openapi()["paths"]


def test_metrics_answers_while_the_default_threadpool_is_exhausted(app):
    """R24: con el limiter de anyio agotado (el caso que mide
    `itcj_anyio_threadpool_waiting`), el scrape NO hace cola detrás de los
    endpoints `def`. Si la hiciera, Prometheus quedaría ciego justo en la
    saturación y la alerta de threadpool nunca llegaría a disparar.

    Un solo event loop (el de `asyncio.run`) para la app y para el hilo que
    acapara el token: el limiter por defecto es POR loop, y el `TestClient`
    sin `with` abre uno nuevo en cada petición.
    """
    import asyncio
    import threading

    import anyio
    import anyio.to_thread
    import httpx

    release = threading.Event()
    holding = threading.Event()

    def _hold_the_only_token():
        holding.set()
        release.wait(10)

    async def _scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 1
        holder = asyncio.create_task(anyio.to_thread.run_sync(_hold_the_only_token))
        try:
            while not holding.is_set():
                await asyncio.sleep(0.005)
            assert limiter.borrowed_tokens == limiter.total_tokens == 1
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
                with anyio.fail_after(5):
                    return await http.get("/metrics")
        finally:
            release.set()
            await holder

    resp = asyncio.run(_scenario())

    assert resp.status_code == 200
    assert resp.headers["content-type"] == CONTENT_TYPE_LATEST


def test_scrape_limiter_is_one_token_per_event_loop():
    # Un CapacityLimiter pertenece a UN loop: reusarlo en otro rompería. En
    # el mismo loop, el mismo limiter (es lo que serializa los scrapes).
    import asyncio

    async def _twice():
        return metrics.scrape_limiter(), metrics.scrape_limiter()

    first_a, first_b = asyncio.run(_twice())
    second, _ = asyncio.run(_twice())

    assert first_a is first_b
    assert first_a is not second
    assert first_a.total_tokens == 1


def test_extra_scrape_collectors_are_rendered(client, monkeypatch):
    # Punto de extensión para colectores evaluados a la hora del scrape
    # (Task 8: presencia y sockets, solo en el rol socket/all).
    class _Probe:
        def collect(self):
            family = GaugeMetricFamily("itcj_scrape_probe", "Sonda del test.")
            family.add_metric([], 42)
            yield family

    monkeypatch.setattr(metrics, "_scrape_collectors", [])
    metrics.register_scrape_collector(_Probe())

    body = client.get("/metrics").text

    assert "itcj_scrape_probe 42.0" in body
