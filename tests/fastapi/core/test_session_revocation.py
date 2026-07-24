"""Phase 8: revocación de sesión vía claim `sv` + versión en Redis."""
import time

import jwt

from itcj2.core.services import session_service as ss

SECRET = "test-secret-key"  # == TEST_SECRET del conftest (middleware parcheado)


def _tok(uid, sv=None):
    now = int(time.time())
    p = {"sub": str(uid), "role": "admin", "name": "x", "cn": None, "iat": now, "exp": now + 3600}
    if sv is not None:
        p["sv"] = sv
    return jwt.encode(p, SECRET, algorithm="HS256")


def test_version_bump():
    uid = 5550001
    assert ss.current_version(uid) == 0
    assert ss.bump_version(uid) == 1
    assert ss.current_version(uid) == 1


def test_token_revoked_after_bump(app_client):
    uid = 5550002
    tok = _tok(uid, sv=0)
    ok = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert ok.status_code == 200                      # sv coincide con la versión (0)
    ss.bump_version(uid)                               # revoca → versión pasa a 1
    revoked = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert revoked.status_code == 401                 # sv(0) != versión(1) → revocado


def test_token_without_sv_not_revoked(app_client):
    uid = 5550003
    ss.bump_version(uid)                               # aunque la versión sea 1...
    tok = _tok(uid, sv=None)                           # ...un token viejo SIN sv no se revisa
    r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200                        # compat hacia atrás
