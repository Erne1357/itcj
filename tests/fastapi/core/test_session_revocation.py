"""Phase 8: revocación de sesión vía claim `sv` + época en Postgres."""
import time

import jwt
import pytest

from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss

SECRET = "test-secret-key"  # == TEST_SECRET del conftest (middleware parcheado)


def _tok(uid, sv=None):
    now = int(time.time())
    p = {"sub": str(uid), "role": "admin", "name": "x", "cn": None, "iat": now, "exp": now + 3600}
    if sv is not None:
        p["sv"] = sv
    return jwt.encode(p, SECRET, algorithm="HS256")


@pytest.fixture()
def user(db_session):
    u = User(first_name="Rev", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    yield u
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=u.id))
    except Exception:
        pass


def test_version_bump(user, db_session, patched_session_local):
    assert ss.current_version(user.id) == 0
    assert ss.bump_version(user.id, db=db_session) == 1
    assert ss.current_version(user.id) == 1


def test_token_revoked_after_bump(app_client, user, db_session, patched_session_local):
    tok = _tok(user.id, sv=0)
    ok = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert ok.status_code == 200                      # sv coincide con la época (0)
    ss.bump_version(user.id, db=db_session)           # revoca → época pasa a 1
    revoked = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert revoked.status_code == 401                 # sv(0) != época(1) → revocado


def test_token_without_sv_not_revoked(app_client, user, db_session, patched_session_local):
    ss.bump_version(user.id, db=db_session)           # aunque la época sea 1...
    tok = _tok(user.id, sv=None)                      # ...un token viejo SIN sv no se revisa
    r = app_client.get("/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200                       # compat hacia atrás
