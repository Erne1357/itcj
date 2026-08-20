"""R5: una caída de Redis NO debe desloguear a nadie.

Antes, `current_version` devolvía 0 tanto si la clave no existía como si Redis
estaba caído. Con Redis caído, todo token con sv>=1 dejaba de coincidir → logout
global. El docstring del módulo afirmaba lo contrario ("fail-open").
"""
import time
from unittest.mock import patch

import jwt

from itcj2.core.services import session_service as ss

SECRET = "test-secret-key"  # == TEST_SECRET del conftest (middleware parcheado)


def _tok(uid, sv):
    now = int(time.time())
    return jwt.encode(
        {"sub": str(uid), "role": "admin", "name": "x", "cn": None,
         "iat": now, "exp": now + 3600, "sv": sv},
        SECRET, algorithm="HS256",
    )


def test_current_version_returns_none_when_redis_errors(monkeypatch):
    """Ni Redis ni Postgres pueden responder: sin informacion, no se revoca.

    Ambos almacenes LANZAN. Ese es el unico caso de None: un uid inexistente con
    la consulta sana vale 0, no None (ver test_missing_user_is_zero_not_none en
    test_session_epoch_durability.py), asi que la BD tiene que romperse de
    verdad para ejercitar este camino.
    """
    class _Boom:
        def get(self, *a, **k):
            raise ConnectionError("redis caido")

    class _DbBoom:
        def execute(self, *a, **k):
            raise ConnectionError("postgres caido")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _DbBoom())
    with patch.object(ss, "_redis", return_value=_Boom()):
        assert ss.current_version(1234567) is None


def test_current_version_falls_back_to_postgres_when_redis_is_empty(db_session, patched_session_local):
    """MISS en Redis no es "versión 0": es "lee la fuente de verdad"."""
    from itcj2.core.models.user import User

    u = User(first_name="Fallback", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    ss.bump_version(u.id, db=db_session)
    db_session.flush()

    class _Empty:
        def get(self, *a, **k):
            return None

    with patch.object(ss, "_redis", return_value=_Empty()):
        assert ss.current_version(u.id) == 1


def test_token_survives_redis_outage(app_client):
    """Con Redis caído, un token con sv>=1 sigue autenticando."""
    tok = _tok(5559201, sv=3)
    with patch.object(ss, "current_version", return_value=None):
        r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200


class _StubUserRow:
    """Fila mínima para el bloque de refresh de middleware.py: is_active=True
    fuerza que NO se enmascare el chequeo de current_version en :112-114
    (`if not _user_active: return response` corta antes de llegar ahí). role
    debe ser genuinamente None (no un MagicMock) porque fluye al payload del
    JWT: `_global_role = _u.role.name if _u.role else None`."""
    is_active = True
    role = None


class _StubDB:
    def get(self, model, pk):
        return _StubUserRow()

    def rollback(self):
        pass

    def close(self):
        pass


def test_refresh_does_not_rotate_cookie_when_version_unknown(app_client):
    """R5 en el bloque de refresh de middleware.py (:115-125 antes de esta tarea):
    si `current_version` no puede determinar la versión vigente, el refresh de
    cookie NO debe acuñar un sv inventado — debe devolver la respuesta sin rotar.

    Token dentro de la ventana de refresh (exp - now < JWT_REFRESH_THRESHOLD_SECONDS
    = 7200s) para forzar `needs_refresh = True`. SessionLocal se stubea (no una fila
    real de core_users) para que `_user_active` sea True sin depender de la BD.

    Contra el código previo a la Tarea 4, `current_version(...)` se pasaba directo
    al payload (`"sv": None`) y SÍ se rotaba la cookie -> este test falla ahí porque
    encuentra un Set-Cookie con itcj_token cuando no debería haber ninguno.
    """
    uid = 5559202
    now = int(time.time())
    tok = jwt.encode(
        {"sub": str(uid), "role": "admin", "name": "x", "cn": None,
         "iat": now, "exp": now + 3600},  # < 7200s: dispara needs_refresh
        SECRET, algorithm="HS256",
    )
    with patch("itcj2.database.SessionLocal", return_value=_StubDB()), \
         patch.object(ss, "current_version", return_value=None):
        r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200
    assert "itcj_token" not in r.cookies
