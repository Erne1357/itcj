"""Phase 8: revocación de sesión vía claim `sv` + versión en Redis."""
import time

import pytest
import jwt

from itcj2.core.services import session_service as ss

SECRET = "test-secret-key"  # == TEST_SECRET del conftest (middleware parcheado)


def _tok(uid, sv=None):
    now = int(time.time())
    p = {"sub": str(uid), "role": "admin", "name": "x", "cn": None, "iat": now, "exp": now + 3600}
    if sv is not None:
        p["sv"] = sv
    return jwt.encode(p, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def _cleanup_session_keys():
    """Borra las claves de sesión de ESTE módulo al terminar.

    El conftest ya no barre `sessionver` (ver tests/fastapi/conftest.py), así que
    cada test de sesión limpia lo suyo en vez de flushear un glob.
    """
    yield
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        r.delete(*[ss._KEY.format(uid=u) for u in (5550001, 5550002, 5550003)])
    except Exception:
        pass


def test_version_bump():
    uid = 5550001
    base = ss.current_version(uid)
    assert ss.bump_version(uid) == base + 1
    assert ss.current_version(uid) == base + 1


def test_token_revoked_after_bump(app_client):
    uid = 5550002
    tok = _tok(uid, sv=ss.current_version(uid))    # sea cual sea la versión vigente
    ok = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert ok.status_code == 200                      # sv coincide con la versión
    ss.bump_version(uid)                              # revoca → versión +1
    revoked = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert revoked.status_code == 401                 # sv != versión → revocado


def test_token_without_sv_not_revoked(app_client):
    uid = 5550003
    ss.bump_version(uid)                               # aunque la versión sea 1...
    tok = _tok(uid, sv=None)                           # ...un token viejo SIN sv no se revisa
    r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200                        # compat hacia atrás
