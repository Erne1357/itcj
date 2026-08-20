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


def test_current_version_returns_none_when_redis_errors():
    class _Boom:
        def get(self, *a, **k):
            raise ConnectionError("redis caido")

    with patch.object(ss, "_redis", return_value=_Boom()):
        assert ss.current_version(1234567) is None


def test_current_version_returns_zero_when_key_absent():
    """Ausencia de clave sigue siendo 0: el usuario nunca fue bumpeado."""
    class _Empty:
        def get(self, *a, **k):
            return None

    with patch.object(ss, "_redis", return_value=_Empty()):
        assert ss.current_version(1234568) == 0


def test_token_survives_redis_outage(app_client):
    """Con Redis caído, un token con sv>=1 sigue autenticando."""
    tok = _tok(5559201, sv=3)
    with patch.object(ss, "current_version", return_value=None):
        r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200
