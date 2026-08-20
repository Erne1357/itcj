"""Dos carreras que dejaban sesiones vivas después de revocarlas.

(a) `toggle_user_status` commiteaba `is_active=False` y bumpeaba DESPUÉS: en el
    hueco, el refresh del middleware podía emitir un token válido y sincronizado.
(b) El logout bumpea, pero si ese mismo request estaba en la ventana de refresh el
    middleware re-emitía la cookie con el `sv` nuevo — logout inefectivo.
(c) `bump_version(db=...)` borra la clave de Redis ANTES de que el caller
    commitee. Un lector que cae en esa ventana rellena el caché con la época
    vieja leída de Postgres (todavía no commiteado) — y como escribir sobre una
    clave ausente es una subida legítima, la guarda monótona no la rechaza.
"""
import time

import jwt
import pytest

from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss

SECRET = "test-secret-key"


@pytest.fixture()
def user(db_session):
    u = User(first_name="Race", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    yield u
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=u.id))
    except Exception:
        pass


def _tok_near_expiry(uid, sv):
    """Token dentro de la ventana de refresh (quedan < JWT_REFRESH_THRESHOLD_SECONDS)."""
    now = int(time.time())
    return jwt.encode(
        {"sub": str(uid), "role": "admin", "name": "x", "cn": None,
         "iat": now, "exp": now + 600, "sv": sv},
        SECRET, algorithm="HS256",
    )


def test_logout_is_not_undone_by_cookie_refresh(app_client, user, db_session, patched_session_local):
    tok = _tok_near_expiry(user.id, sv=ss.current_version(user.id))
    resp = app_client.post("/api/core/v2/auth/logout", headers={"Cookie": f"itcj_token={tok}"})
    assert resp.status_code == 204

    # El middleware NO debe haber rotado la cookie a un token válido nuevo. El
    # borrado de cookie sí aparece como Set-Cookie, pero con valor vacío.
    minted = [
        c for c in resp.headers.get_list("set-cookie")
        if c.startswith("itcj_token=")
        and c.split(";")[0].split("=", 1)[1].strip('"') != ""
    ]
    assert minted == [], f"el refresh re-emitio la cookie tras el logout: {minted}"


def test_deactivation_revokes_in_the_same_transaction(user, db_session, patched_session_local):
    """Tras desactivar, la época ya está incrementada en la misma transacción."""
    from itcj2.core.services.session_service import bump_version

    user.is_active = False
    bump_version(user.id, db=db_session)
    db_session.flush()
    # El bump es SQL crudo: el identity map conserva el 0 que el INSERT trajo por
    # RETURNING. Expirar obliga a releer la fila real dentro de la transacción
    # (mismo patrón que test_session_epoch_durability.py:40).
    db_session.expire(user)

    assert db_session.get(User, user.id).session_epoch == 1
    assert db_session.get(User, user.id).is_active is False


def test_forget_cached_version_closes_the_bump_db_window(user, db_session, patched_session_local):
    """A6: reproduce la ventana entre el DELETE de `bump_version(db=...)` y el
    commit del caller.

    Simula un lector que cae exactamente en esa ventana: rellena el caché con la
    época vieja (0) leída de Postgres todavía no commiteado. Sin el segundo
    borrado (`forget_cached_version`), esa entrada sobrevive hasta el TTL y sirve
    la época vieja aunque el caller ya haya commiteado la N nueva.
    """
    from itcj2.core.utils.redis_conn import get_redis

    assert ss.current_version(user.id) == 0

    # bump_version(db=...) corre el UPDATE en la transacción del test y borra la
    # clave de Redis (el caller, este test, todavía no commiteó).
    new_epoch = ss.bump_version(user.id, db=db_session)
    assert new_epoch == 1

    # Ventana: un lector cae aquí, no ve el commit, y repuebla el caché con la
    # época vieja (0) que SÍ puede leer de Postgres (autoflush ve la fila
    # modificada dentro de la misma transacción, pero para este test simulamos
    # directamente el efecto: el lector escribe 0 en una clave ausente).
    r = get_redis()
    r.eval(ss._SET_IF_GREATER, 1, ss._KEY.format(uid=user.id), 0, ss._TTL)
    assert ss.current_version(user.id) == 0  # el lector quedó satisfecho con la época vieja

    # El caller commitea y cierra la ventana con el segundo borrado.
    db_session.flush()
    ss.forget_cached_version(user.id)

    # El siguiente lector ya no debe ver la época vieja cacheada.
    assert ss.current_version(user.id) == 1
