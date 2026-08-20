"""R6: la revocación de sesión sobrevive a la pérdida de Redis.

Postgres (`core_users.session_epoch`) es la fuente de verdad; Redis es solo un
caché read-through con TTL.
"""
import pytest

from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss


@pytest.fixture()
def user(db_session):
    u = User(first_name="Epoch", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    yield u
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=u.id))
    except Exception:
        pass


def test_bump_persists_to_postgres(user, db_session, patched_session_local):
    ss.bump_version(user.id, db=db_session)
    db_session.flush()
    # El bump es SQL crudo: el identity map conserva el 0 que el INSERT trajo por
    # RETURNING. Expirar obliga a releer la fila real dentro de la transaccion.
    db_session.expire(user)

    assert db_session.get(User, user.id).session_epoch == 1


def test_current_version_reads_postgres_when_redis_is_empty(user, db_session, patched_session_local):
    """El caso que hoy desloguea: Redis perdió la clave, Postgres la conserva."""
    ss.bump_version(user.id, db=db_session)
    db_session.flush()
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=user.id))
    except Exception:
        pass

    assert ss.current_version(user.id) == 1


def test_default_epoch_is_zero(user, patched_session_local):
    assert ss.current_version(user.id) == 0
