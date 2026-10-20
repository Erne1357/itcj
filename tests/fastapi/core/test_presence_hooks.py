"""Hooks de presencia del namespace /notify + broadcast active_users a /system."""
import asyncio
import time
from unittest.mock import patch

import pytest

from itcj2.config import get_settings
from itcj2.core.services import presence_service as ps
from itcj2.core.utils.redis_conn import get_redis
from itcj2.sockets.notifications import HEARTBEAT_EVENT, register_notification_namespace

from ._socket_fakes import FakeSio, environ_for


def _flush_presence(client):
    keys = list(client.scan_iter(match="presence:notify:*", count=100))
    keys += list(client.scan_iter(match="presence:app:*", count=100))
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


# ---------------------------------------------------------------------------
# Latido del shell (ronda 3): la presencia deja de decaer con la sesión viva
# ---------------------------------------------------------------------------
def _beat(fake, sid, payload):
    return asyncio.run(fake.handlers[("/notify", HEARTBEAT_EVENT)](sid, payload))


def test_latido_marca_la_app_reportada(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    asyncio.run(on_connect("sid1", environ_for(9920011)))
    _beat(fake, "sid1", {"app": "helpdesk"})
    assert ps.get_app_counts(r)["helpdesk"] == 1


def test_latido_sin_payload_o_con_app_desconocida_cae_en_otro(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    asyncio.run(on_connect("sidA", environ_for(9920012)))
    asyncio.run(on_connect("sidB", environ_for(9920013)))
    _beat(fake, "sidA", None)
    _beat(fake, "sidB", {"app": "inventada"})
    assert ps.get_app_counts(r)["otro"] == 2


def test_latido_sin_app_abierta_reporta_core(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    asyncio.run(on_connect("sid1", environ_for(9920014)))
    _beat(fake, "sid1", {"app": "core"})
    assert ps.get_app_counts(r)["core"] == 1


def test_latido_de_socket_no_autenticado_no_marca_nada(fake, r):
    _beat(fake, "sid-fantasma", {"app": "helpdesk"})
    assert ps.get_counts(r)["total"] == 0
    assert ps.get_app_counts(r)["helpdesk"] == 0


def test_el_latido_revive_una_presencia_a_punto_de_podarse(fake, r):
    """El bug de producción: sockets abiertos con presencia 0 el 93,7 % del tiempo.

    La marca del `connect` sale de la ventana y la lectura la poda aunque el
    usuario siga dentro; el latido la vuelve a meter.
    """
    on_connect = fake.handlers[("/notify", "connect")]
    asyncio.run(on_connect("sid1", environ_for(9920015)))
    window = get_settings().PRESENCE_WINDOW_SECONDS
    r.zadd("presence:notify:staff", {"9920015": time.time() - window - 10})
    assert ps.get_counts(r)["staff"] == 0
    _beat(fake, "sid1", {"app": "helpdesk"})
    assert ps.get_counts(r)["staff"] == 1


def test_cambio_de_app_entre_latidos_no_deja_fantasma(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    asyncio.run(on_connect("sid1", environ_for(9920016)))
    _beat(fake, "sid1", {"app": "helpdesk"})
    _beat(fake, "sid1", {"app": "maint"})
    counts = ps.get_app_counts(r)
    assert counts["helpdesk"] == 0
    assert counts["maint"] == 1


def test_disconnect_limpia_tambien_la_app(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    on_disconnect = fake.handlers[("/notify", "disconnect")]
    asyncio.run(on_connect("sid1", environ_for(9920017)))
    _beat(fake, "sid1", {"app": "titulatec"})
    asyncio.run(on_disconnect("sid1"))
    assert ps.get_counts(r)["staff"] == 0
    assert ps.get_app_counts(r)["titulatec"] == 0


def test_disconnect_con_otra_pestana_retira_solo_la_app_de_ese_socket(fake, r):
    on_connect = fake.handlers[("/notify", "connect")]
    on_disconnect = fake.handlers[("/notify", "disconnect")]
    asyncio.run(on_connect("sidA", environ_for(9920018)))
    asyncio.run(on_connect("sidB", environ_for(9920018)))
    _beat(fake, "sidA", {"app": "helpdesk"})
    _beat(fake, "sidB", {"app": "maint"})
    asyncio.run(on_disconnect("sidA"))
    counts = ps.get_app_counts(r)
    assert ps.get_counts(r)["staff"] == 1   # sigue dentro por la otra pestaña
    assert counts["helpdesk"] == 0
    assert counts["maint"] == 1


def test_latido_con_redis_caido_no_rompe_el_handler(fake):
    fake.sessions[("/notify", "sid1")] = {
        "user": {"sub": "9920019", "role": "staff"},
        "bucket": "staff",
    }
    with patch("itcj2.sockets.notifications._redis", side_effect=RuntimeError("down")):
        _beat(fake, "sid1", {"app": "helpdesk"})   # no propaga la excepción
