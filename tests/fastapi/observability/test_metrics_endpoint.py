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
