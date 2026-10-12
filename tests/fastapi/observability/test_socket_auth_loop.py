"""El handshake de Socket.IO no hace E/S síncrona en el event loop.

`current_user_from_environ` corre dentro del handler `connect` de los 6
namespaces, en el loop único del contenedor `sockets`. Con `sv` en el token
consultaba `session_service.current_version` (Redis y, con el caché frío,
Postgres) SIN await: una ráfaga de conexiones a `/slots` congelaba el loop. Mismo
bug que la Fase 6 arregló en `JWTMiddleware`, mismo espía.

El `connect` se despacha por `_trigger_event` del `AsyncServer` real, como hace
`_handle_connect`, sin red. Los uids ficticios no tocan Postgres.
"""
import asyncio
import pathlib
from unittest.mock import patch

import pytest

from itcj2.core.services import session_service as ss
from itcj2.core.utils import socket_auth
from itcj2.core.utils.jwt_tools import encode_jwt
from itcj2.sockets.helpdesk import register_helpdesk_namespace
from itcj2.sockets.instrumentation import InstrumentedAsyncServer
from itcj2.sockets.maint import register_maint_namespace

pytestmark = pytest.mark.asyncio

_UID = 5661020  # ficticio: sus claves de Redis se borran al terminar


def _environ(**claims) -> dict:
    payload = {"sub": str(_UID), "role": "staff", "cn": None, "name": "X", **claims}
    return {"HTTP_COOKIE": f"itcj_token={encode_jwt(payload, hours=1)}"}


@pytest.fixture(autouse=True)
def _clean_key():
    def _drop():
        try:
            from itcj2.core.utils.redis_conn import get_redis
            get_redis().delete(ss._KEY.format(uid=_UID))
        except Exception:
            pass
    _drop()
    yield
    _drop()


@pytest.mark.parametrize(
    "register,namespace",
    [(register_helpdesk_namespace, "/helpdesk"), (register_maint_namespace, "/maint")],
)
async def test_connect_does_no_sync_io_on_the_event_loop(
    register, namespace, monkeypatch
):
    """Se registra quién llama a la E/S síncrona con un loop corriendo EN SU
    HILO: tiene que ser nadie. Se registra en vez de lanzar porque el chequeo
    de `sv` se traga cualquier excepción (fail-open) y el test no vería nada.
    Caché frío: obliga al MISS que va a Postgres, el peor caso."""
    from itcj2 import database
    from itcj2.core.utils import redis_conn

    on_loop: list[str] = []

    def _on_loop() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def _spy(name, fn):
        def wrapper(*a, **k):
            if _on_loop():
                on_loop.append(name)
            return fn(*a, **k)
        return wrapper

    monkeypatch.setattr(ss, "current_version", _spy("current_version", ss.current_version))
    monkeypatch.setattr(ss, "_read_epoch_from_db", _spy("_read_epoch_from_db", ss._read_epoch_from_db))
    monkeypatch.setattr(database, "SessionLocal", _spy("SessionLocal", database.SessionLocal))
    monkeypatch.setattr(redis_conn, "get_redis", _spy("get_redis", redis_conn.get_redis))

    sio = InstrumentedAsyncServer(async_mode="asgi")
    register(sio)
    sessions = {}

    async def _save_session(sid, session, namespace=None):
        sessions[sid] = session

    async def _emit(*a, **k):
        pass

    monkeypatch.setattr(sio, "save_session", _save_session)
    monkeypatch.setattr(sio, "emit", _emit)

    result = await sio._trigger_event("connect", namespace, "s1", _environ(sv=0))

    assert result is not False          # el handshake siguió aceptándose
    assert sessions["s1"]["user"]["sub"] == str(_UID)
    assert on_loop == []


async def test_sv_vigente_devuelve_el_usuario():
    with patch.object(ss, "current_version_async", return_value=3):
        user = await socket_auth.current_user_from_environ(_environ(sv=3))
    assert user == {"sub": str(_UID), "role": "staff", "cn": None, "name": "X"}


async def test_sv_desajustado_devuelve_none():
    with patch.object(ss, "current_version_async", return_value=4):
        assert await socket_auth.current_user_from_environ(_environ(sv=3)) is None


async def test_almacen_caido_none_no_revoca():
    with patch.object(ss, "current_version_async", return_value=None):
        user = await socket_auth.current_user_from_environ(_environ(sv=99))
    assert user is not None and user["sub"] == str(_UID)


async def test_excepcion_del_almacen_no_revoca():
    with patch.object(ss, "current_version_async", side_effect=RuntimeError("redis down")):
        assert await socket_auth.current_user_from_environ(_environ(sv=99)) is not None


async def test_token_sin_sv_no_consulta_el_almacen():
    with patch.object(ss, "current_version_async") as consulta:
        user = await socket_auth.current_user_from_environ(_environ())
    assert user is not None
    consulta.assert_not_called()


@pytest.mark.parametrize("modulo", ["helpdesk", "maint", "notifications", "requests", "slots", "system"])
async def test_los_seis_namespaces_esperan_la_autenticacion(modulo):
    """Sin `await` el handler recibiría una corrutina (truthy) y dejaría pasar a
    cualquiera: el guard es estático porque ningún test de connect cubre los seis."""
    src = (pathlib.Path(__file__).parents[3] / "itcj2" / "sockets" / f"{modulo}.py").read_text(encoding="utf-8")
    assert "await current_user_from_environ(" in src
    assert "= current_user_from_environ(" not in src
