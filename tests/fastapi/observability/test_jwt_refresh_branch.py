"""Caracterización de `JWTMiddleware` contra Redis y Postgres reales (Fase 6).

Fija el comportamiento que sacar del event loop la E/S síncrona del middleware
NO puede romper: la rotación de la cookie (rol GLOBAL string, `sv` vigente),
el usuario inactivo, la época indeterminable y la revocación por `sv`.

La app bajo prueba vive dentro de pytest, así que lee la db 15 de Redis que
fija `tests/fastapi/conftest.py`; Postgres va por `patched_session_local`, que
hace que el `SessionLocal()` del middleware y de `session_service` vean las
filas creadas dentro de la transacción del test.
"""
import time

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from unittest.mock import patch

from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss
from tests.conftest import TEST_SECRET

WHOAMI = "/__test__/whoami"


@pytest.fixture()
def client():
    """App real más un endpoint que devuelve `request.state.current_user` tal
    cual lo dejó el middleware: es lo que se quiere observar, no lo que una
    ruta de negocio decida hacer con ello."""
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()

        @app.get(WHOAMI)
        async def _whoami(request: Request):
            return {"current_user": request.state.current_user}

        with TestClient(app) as c:
            yield c


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """Copia de la de `tests/fastapi/core/conftest.py` (los conftest de un
    directorio hermano no se ven desde aquí). `close()` y `rollback()` son no-op
    porque el middleware y `session_service` los llaman creyendo que la sesión es
    suya: un rollback volvería al SAVEPOINT y BORRARÍA el usuario del test."""
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session


def _role(db_session, name: str) -> Role:
    return db_session.execute(select(Role).where(Role.name == name)).scalar_one()


@pytest.fixture()
def user(db_session):
    u = User(
        first_name="Refresh",
        last_name="Test",
        is_active=True,
        role_id=_role(db_session, "student").id,
    )
    db_session.add(u)
    db_session.flush()
    yield u
    # Borra SOLO su uid: un glob sobre `session:v1:ver:*` desloguearía a usuarios
    # reales si la suite corre contra un Redis compartido.
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=u.id))
    except Exception:
        pass


def _token(uid: int, *, ttl: int, sv: int | None = None, role="admin") -> str:
    now = int(time.time())
    payload = {"sub": str(uid), "role": role, "name": "x", "cn": None,
               "iat": now, "exp": now + ttl}
    if sv is not None:
        payload["sv"] = sv
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def _near_expiry(uid: int, **kw) -> str:
    """Le quedan 10 min: dentro de JWT_REFRESH_THRESHOLD_SECONDS (2 h)."""
    return _token(uid, ttl=600, **kw)


def _minted(resp) -> list[str]:
    """Valores no vacíos de `itcj_token` en los Set-Cookie (un borrado no cuenta)."""
    out = []
    for c in resp.headers.get_list("set-cookie"):
        if c.startswith("itcj_token="):
            val = c.split(";")[0].split("=", 1)[1].strip('"')
            if val:
                out.append(val)
    return out


def _bump(user, db_session) -> int:
    v = ss.bump_version(user.id, db=db_session)
    db_session.flush()
    ss.forget_cached_version(user.id)
    return v


def test_refresh_rotates_cookie_with_global_role_and_current_epoch(
    client, user, db_session, patched_session_local
):
    epoch = _bump(user, db_session)
    assert epoch == 1

    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={_near_expiry(user.id, sv=epoch)}"})

    assert resp.status_code == 200
    minted = _minted(resp)
    assert len(minted) == 1, resp.headers.get_list("set-cookie")
    claims = jwt.decode(minted[0], TEST_SECRET, algorithms=["HS256"])
    # El rol GLOBAL de la fila, no el «admin» que traía el token ni una lista.
    assert claims["role"] == "student"
    assert claims["sv"] == epoch
    assert claims["sub"] == str(user.id)
    assert claims["exp"] - int(time.time()) > 3600


def test_refresh_does_not_rotate_for_inactive_user(
    client, user, db_session, patched_session_local
):
    user.is_active = False
    db_session.flush()

    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={_near_expiry(user.id, sv=0)}"})

    assert resp.status_code == 200
    assert _minted(resp) == []


def test_refresh_does_not_rotate_when_epoch_is_undeterminable(
    client, user, db_session, patched_session_local, monkeypatch
):
    """Redis inalcanzable DE VERDAD (puerto cerrado) y la lectura de Postgres de
    la época fallando: `current_version` → None y no se acuña un `sv` inventado.

    Token SIN `sv` a propósito: así el único consumidor de la época es el bloque
    de refresh, que es lo que este caso fija."""
    import redis

    from itcj2.core.utils import redis_conn

    monkeypatch.setattr(
        redis_conn, "_redis",
        redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2,
                    decode_responses=True),
    )
    monkeypatch.setattr(ss, "_read_epoch_from_db", lambda uid: None)
    assert ss.current_version(user.id) is None

    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={_near_expiry(user.id)}"})

    assert resp.status_code == 200
    assert resp.json()["current_user"]["sub"] == str(user.id)
    assert _minted(resp) == []


def test_stale_sv_leaves_no_current_user(client, user, db_session, patched_session_local):
    _bump(user, db_session)  # época 1

    # Fuera de la ventana de refresh: lo observado es SOLO la revocación.
    tok = _token(user.id, ttl=6 * 3600, sv=0)
    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={tok}"})

    assert resp.status_code == 200
    assert resp.json() == {"current_user": None}
    assert _minted(resp) == []


def test_token_without_sv_skips_epoch_lookup(client, user, monkeypatch):
    """Compat con tokens previos a `sv`: ni se consulta la época, ni se revoca."""
    calls = []

    def _spy(*a, **k):
        calls.append(a)
        return 99

    async def _spy_async(*a, **k):
        calls.append(a)
        return 99

    monkeypatch.setattr(ss, "current_version", _spy)
    monkeypatch.setattr(ss, "current_version_async", _spy_async, raising=False)

    tok = _token(user.id, ttl=6 * 3600)
    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={tok}"})

    assert resp.status_code == 200
    body = resp.json()["current_user"]
    assert body["sub"] == str(user.id)
    assert body["role"] == "admin"
    assert "sv" not in body
    assert calls == []


def test_dispatch_does_no_sync_io_on_the_event_loop(
    client, user, db_session, patched_session_local, monkeypatch
):
    """Fase 6: `dispatch` corre en el loop para TODA petición; una consulta
    síncrona ahí frena todas las peticiones en vuelo del worker (alerta
    `ItcjEventLoopBloqueosLargos`). Se registra quién llama a la E/S síncrona
    con un loop corriendo EN SU HILO: tiene que ser nadie.

    Se registra en vez de lanzar porque el primer chequeo de `sv` del
    middleware se traga cualquier excepción (fail-open) y el test no vería nada.
    Token con `sv` y dentro de la ventana de refresh: recorre los TRES sitios.
    """
    import asyncio

    from itcj2 import database

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
    from itcj2.core.utils import redis_conn
    monkeypatch.setattr(redis_conn, "get_redis", _spy("get_redis", redis_conn.get_redis))

    # Caché frío: obliga al MISS que va a Postgres, el peor caso.
    ss.forget_cached_version(user.id)
    resp = client.get(WHOAMI, headers={"Cookie": f"itcj_token={_near_expiry(user.id, sv=0)}"})

    assert resp.status_code == 200
    assert resp.json()["current_user"]["sub"] == str(user.id)
    assert len(_minted(resp)) == 1  # el refresh siguió funcionando
    assert on_loop == []


def test_current_version_async_matches_sync_semantics(user, db_session, patched_session_local):
    """MISS → Postgres y repuebla el caché; HIT → Redis. Cada `asyncio.run` es
    un loop nuevo: también fija que el cliente async no queda atado al primero."""
    import asyncio

    from itcj2.core.utils.redis_conn import get_redis

    epoch = _bump(user, db_session)  # deja el caché vacío
    assert asyncio.run(ss.current_version_async(user.id)) == epoch == ss.current_version(user.id)
    assert get_redis().get(ss._KEY.format(uid=user.id)) == str(epoch)  # repoblado

    get_redis().set(ss._KEY.format(uid=user.id), 7, ex=60)
    assert asyncio.run(ss.current_version_async(user.id)) == 7  # HIT, otro loop


def test_current_version_async_is_none_only_when_both_stores_fail(monkeypatch):
    import asyncio

    from itcj2.core.utils import redis_conn

    monkeypatch.setattr(redis_conn, "REDIS_URL", "redis://127.0.0.1:1/15")
    monkeypatch.setattr(ss, "_read_epoch_from_db", lambda uid: None)
    assert asyncio.run(ss.current_version_async(1234567)) is None

    monkeypatch.setattr(ss, "_read_epoch_from_db", lambda uid: 0)
    assert asyncio.run(ss.current_version_async(1234567)) == 0  # inexistente ≠ None
