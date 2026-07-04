"""Hooks de presencia del namespace /notify + broadcast active_users a /system."""
import asyncio
from unittest.mock import patch

import pytest

from itcj2.core.services import presence_service as ps
from itcj2.core.utils.redis_conn import get_redis
from itcj2.sockets.notifications import register_notification_namespace

from ._socket_fakes import FakeSio, environ_for


def _flush_presence(client):
    keys = list(client.scan_iter(match="presence:notify:*", count=100))
    if keys:
        client.delete(*keys)


@pytest.fixture()
def r():
    client = get_redis()
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    _flush_presence(client)
    yield client
    _flush_presence(client)


@pytest.fixture()
def fake():
    sio_fake = FakeSio()
    register_notification_namespace(sio_fake)
    return sio_fake


def _system_broadcasts(fake):
    return [e for e in fake.emitted if e["event"] == "active_users" and e["namespace"] == "/system"]


def test_connect_marca_online_y_broadcastea(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    result = asyncio.run(on_connect("sid1", environ_for(9920001, role="admin")))
    assert result is not False
    assert ps.get_counts(r)["admins"] == 1
    casts = _system_broadcasts(fake)
    assert casts, "connect debe emitir active_users al namespace /system"
    assert casts[-1]["data"]["total"] == 1
    assert casts[-1]["data"]["admins"] == 1
    # el hello por-sid sigue existiendo (compat con widgets actuales)
    assert any(e["event"] == "hello" and e["to"] == "sid1" for e in fake.emitted)


def test_connect_anonimo_rechazado_sin_presencia(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    assert asyncio.run(on_connect("sid1", {"HTTP_COOKIE": ""})) is False
    assert ps.get_counts(r)["total"] == 0


def test_disconnect_ultimo_socket_marca_offline(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    on_disconnect = fake.handlers[("/notify", "disconnect")]
    asyncio.run(on_connect("sid1", environ_for(9920002)))
    assert ps.get_counts(r)["staff"] == 1
    asyncio.run(on_disconnect("sid1"))
    counts = ps.get_counts(r)
    assert counts["staff"] == 0
    assert _system_broadcasts(fake)[-1]["data"]["total"] == 0


def test_disconnect_con_otra_pestana_sigue_online(fake, r):
    """Mismo uid con 2 sockets (2 pestañas): cerrar una NO lo saca del conteo."""
    on_connect = fake.handlers[("/notify", "connect")]
    on_disconnect = fake.handlers[("/notify", "disconnect")]
    asyncio.run(on_connect("sidA", environ_for(9920003)))
    asyncio.run(on_connect("sidB", environ_for(9920003)))
    asyncio.run(on_disconnect("sidA"))
    assert ps.get_counts(r)["staff"] == 1


def test_redis_caido_no_rechaza_el_handshake(fake):
    """La presencia es best-effort: sin Redis el WS de notificaciones sigue vivo."""
    on_connect = fake.handlers[("/notify", "connect")]
    with patch("itcj2.sockets.notifications._redis", side_effect=RuntimeError("down")):
        result = asyncio.run(on_connect("sid1", environ_for(9920004)))
    assert result is not False
    assert any(e["event"] == "hello" for e in fake.emitted)
