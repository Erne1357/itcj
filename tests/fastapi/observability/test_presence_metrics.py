"""`itcj_presence_users` e `itcj_socket_connections` en `/metrics` (Task 8).

Decisión del dueño 2026-09-21: CUÁNTOS conectados, nunca QUIÉNES — ninguna
etiqueta lleva uid ni sid.

Redis REAL del contenedor (como `test_presence_service.py`), pero con un
prefijo de clave PROPIO (`_KEY` de `presence_service` monkeypatcheado): a
diferencia de esos tests, aquí se comparan CONTEOS ABSOLUTOS contra el body
de `/metrics`, y una presencia real del dev (alguien conectado de verdad al
`/notify` del stack) los rompería si se compartiera `presence:notify:*`.

`APP_ROLE` se fija en CADA test con `monkeypatch.setattr(get_settings(),
"APP_ROLE", ...)`, nunca se lee del entorno: el contenedor de dev corre con
`http` (`docker-compose.dev.yml`) pero CI no define la variable y cae en el
default `all`. Un test que dependiera del entorno pasaría en local y
bloquearía el deploy en CI.
"""
import logging

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from itcj2.config import get_settings
from itcj2.core.services import presence_service
from itcj2.core.utils.redis_conn import get_redis
from itcj2.main import create_app

TEST_KEY_TEMPLATE = "test:obs-presence:{bucket}"


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def presence_redis(monkeypatch):
    """Aísla las claves de presencia: prefijo propio (nunca `presence:notify:*`,
    que puede tener presencia real del dev) y limpieza al entrar Y al salir.

    Al entrar también: una corrida abortada (Ctrl+C, contenedor reiniciado)
    no llega al teardown y deja miembros vivos hasta
    `PRESENCE_WINDOW_SECONDS`; la siguiente corrida compararía conteos
    absolutos contra ese residuo y fallaría sin que nada estuviera roto."""
    monkeypatch.setattr(presence_service, "_KEY", TEST_KEY_TEMPLATE)
    client = get_redis()
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    _delete_test_keys(client)
    yield client
    _delete_test_keys(client)


def _delete_test_keys(client) -> None:
    for bucket in presence_service.BUCKETS:
        client.delete(TEST_KEY_TEMPLATE.format(bucket=bucket))


def _family(body: str, name: str):
    for family in text_string_to_metric_families(body):
        if family.name == name:
            return family
    return None


def _label_values(family) -> dict:
    """{único-valor-de-etiqueta: valor} — ambas familias tienen 1 sola etiqueta."""
    return {next(iter(s.labels.values())): s.value for s in family.samples}


# ---------------------------------------------------------------------------
# APP_ROLE=http (backend-blue/green): ninguna familia aparece
# ---------------------------------------------------------------------------
def test_http_role_never_exposes_presence_or_socket_families(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "APP_ROLE", "http")

    body = client.get("/metrics").text

    assert _family(body, "itcj_presence_users") is None
    assert _family(body, "itcj_socket_connections") is None


# ---------------------------------------------------------------------------
# APP_ROLE socket/all: ambas familias aparecen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["socket", "all"])
def test_presence_users_reports_real_counts_per_bucket(
    client, presence_redis, monkeypatch, role
):
    monkeypatch.setattr(get_settings(), "APP_ROLE", role)
    presence_service.mark_online(presence_redis, 9950001, "students")
    presence_service.mark_online(presence_redis, 9950002, "students")
    presence_service.mark_online(presence_redis, 9950003, "staff")
    presence_service.mark_online(presence_redis, 9950004, "admins")

    body = client.get("/metrics").text

    family = _family(body, "itcj_presence_users")
    assert family is not None
    assert _label_values(family) == {
        "students": 2.0,
        "staff": 1.0,
        "admins": 1.0,
        "all": 4.0,
    }


@pytest.mark.parametrize("role", ["socket", "all"])
def test_socket_connections_lists_every_registered_namespace(client, monkeypatch, role):
    monkeypatch.setattr(get_settings(), "APP_ROLE", role)
    from itcj2.sockets.server import sio  # dispara el registro de namespaces

    expected_namespaces = set(sio.handlers)
    assert expected_namespaces, "el paquete itcj2.sockets no registró namespaces"

    body = client.get("/metrics").text

    family = _family(body, "itcj_socket_connections")
    assert family is not None
    values = _label_values(family)
    assert set(values) == expected_namespaces
    # Nadie se conecta al socket real de un TestClient de FastAPI: en este
    # proceso todas las salas están vacías.
    assert all(v == 0.0 for v in values.values())


def test_socket_connections_counts_sids_without_iterating_them(client, monkeypatch):
    # Estructura real de python-socketio 5.17: `rooms[namespace][None]` es la
    # sala implícita con TODOS los sids del namespace (ver base_manager.py).
    # Se verifica que el colector cuenta esa sala con `len()`, no que hace un
    # socket real (fuera de alcance aquí y frágil).
    monkeypatch.setattr(get_settings(), "APP_ROLE", "all")
    from itcj2.sockets.server import sio

    fake_rooms = dict(sio.manager.rooms)
    fake_rooms["/helpdesk"] = {None: {"sidA": "eioA", "sidB": "eioB", "sidC": "eioC"}}
    monkeypatch.setattr(sio.manager, "rooms", fake_rooms)

    body = client.get("/metrics").text

    family = _family(body, "itcj_socket_connections")
    assert _label_values(family)["/helpdesk"] == 3.0


# ---------------------------------------------------------------------------
# Redis caído: /metrics sigue en 200, sin la familia de presencia, y lo loguea
# ---------------------------------------------------------------------------
def test_redis_failure_keeps_200_without_presence_family_and_logs(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(get_settings(), "APP_ROLE", "all")

    def _boom(_r):
        raise ConnectionError("redis caído (simulado)")

    monkeypatch.setattr(presence_service, "get_counts", _boom)

    with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
        resp = client.get("/metrics")

    assert resp.status_code == 200
    assert _family(resp.text, "itcj_presence_users") is None
    # La familia de sockets no depende de Redis: sigue presente.
    assert _family(resp.text, "itcj_socket_connections") is not None
    assert any(
        r.exc_info and "redis caído" in str(r.exc_info[1]) for r in caplog.records
    )


def test_socket_manager_failure_keeps_200_without_socket_family_and_logs(
    client, presence_redis, monkeypatch, caplog
):
    # Reproduce el hallazgo de la revisión: una lectura de `sio.manager.rooms`
    # que explota (estructura corrupta/inesperada, no una caída de Redis) no
    # debe tirar TODO el scrape de /metrics, solo omitir esta familia — mismo
    # contrato que ya cubre `_presence_family()` arriba.
    monkeypatch.setattr(get_settings(), "APP_ROLE", "all")
    from itcj2.sockets.server import sio

    class _BoomRooms:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("rooms corrupto (simulado)")

    monkeypatch.setattr(sio.manager, "rooms", _BoomRooms())

    with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
        resp = client.get("/metrics")

    assert resp.status_code == 200
    assert _family(resp.text, "itcj_socket_connections") is None
    # La familia de presencia no depende de sio.manager: sigue presente.
    assert _family(resp.text, "itcj_presence_users") is not None
    assert any(
        r.exc_info and "rooms corrupto" in str(r.exc_info[1]) for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Nunca identidades: solo bucket/namespace y conteos
# ---------------------------------------------------------------------------
def test_no_user_ids_appear_anywhere_in_the_metrics_body(client, presence_redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "APP_ROLE", "all")
    presence_service.mark_online(presence_redis, 9950099, "staff")

    body = client.get("/metrics").text

    assert "9950099" not in body
    family = _family(body, "itcj_presence_users")
    assert set(_label_values(family)) == {"students", "staff", "admins", "all"}
