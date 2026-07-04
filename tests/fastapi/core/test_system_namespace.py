"""/system es broadcast-only: autentica, manda snapshot al sid y NO contabiliza."""
import asyncio

import pytest

from itcj2.core.services import presence_service as ps
from itcj2.core.utils.redis_conn import get_redis
from itcj2.sockets.system import register_system_namespace

from ._socket_fakes import FakeSio, environ_for

_LEGACY_KEYS = ("socket:active:students", "socket:active:admins")


def _flush(client):
    keys = list(client.scan_iter(match="presence:notify:*", count=100))
    keys += [k for k in _LEGACY_KEYS if client.exists(k)]
    keys += list(client.scan_iter(match="socket:user_sids:993*", count=100))
    if keys:
        client.delete(*keys)


@pytest.fixture()
def r():
    client = get_redis()
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    _flush(client)
    yield client
    _flush(client)


@pytest.fixture()
def fake():
    sio_fake = FakeSio()
    register_system_namespace(sio_fake)
    return sio_fake


def test_connect_emite_snapshot_al_sid(fake, r):
    ps.mark_online(r, 9930001, "staff")  # presencia preexistente (vía /notify)
    on_connect = fake.handlers[("/system", "connect")]
    asyncio.run(on_connect("sidX", environ_for(9930002, role="admin")))
    snaps = [e for e in fake.emitted if e["event"] == "active_users" and e["to"] == "sidX"]
    assert snaps, "connect a /system debe emitir el snapshot al sid entrante"
    assert snaps[-1]["data"] == {"total": 1, "students": 0, "staff": 1, "admins": 0}


def test_connect_anonimo_rechazado(fake):
    on_connect = fake.handlers[("/system", "connect")]
    assert asyncio.run(on_connect("sidX", {"HTTP_COOKIE": ""})) is False


def test_connect_ya_no_escribe_sets_legacy(fake, r):
    on_connect = fake.handlers[("/system", "connect")]
    asyncio.run(on_connect("sidX", environ_for(9930003, role="admin")))
    assert r.scard("socket:active:admins") == 0
    assert r.scard("socket:active:students") == 0
    assert not list(r.scan_iter(match="socket:user_sids:9930003", count=10))


def test_connect_no_marca_presencia_propia(fake, r):
    """Conectarse SOLO a /system (widget) no te vuelve 'activo': eso es de /notify."""
    on_connect = fake.handlers[("/system", "connect")]
    asyncio.run(on_connect("sidX", environ_for(9930004, role="admin")))
    assert ps.get_counts(r)["total"] == 0
