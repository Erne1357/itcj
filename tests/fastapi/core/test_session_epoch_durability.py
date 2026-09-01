"""R6: la revocación de sesión sobrevive a la pérdida de Redis.

Postgres (`core_users.session_epoch`) es la fuente de verdad; Redis es solo un
caché read-through con TTL.
"""
import pytest

from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss


def _redis_or_skip():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        r.ping()
    except Exception:
        pytest.skip("Redis no disponible; no hay caché que probar")
    return r


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


# ---------------------------------------------------------------------------
# C1: el caché nunca puede quedar por DEBAJO de la verdad
# ---------------------------------------------------------------------------
def test_cache_write_never_lowers_the_cached_epoch(user):
    """La guarda monótona: sube, nunca baja.

    Sin ella, dos bumps concurrentes con SETs desordenados —o el SET tardío de
    un lector que leyó Postgres antes de un bump— dejarían en Redis un valor
    menor que el real y una sesión revocada seguiría autenticando hasta el TTL.
    """
    r = _redis_or_skip()
    key = ss._KEY.format(uid=user.id)
    r.setex(key, 60, 5)                     # TTL corto y conocido

    ss._cache_epoch(r, user.id, 3)          # llega tarde y trae un valor viejo
    assert r.get(key) == "5"                # ...se descarta
    # Y el rechazo NO refresca el TTL. Es lo que permite que una clave que quedara
    # ALTA (p.ej. tras un restore de BD que baje la época) se auto-sane al expirar:
    # si el rechazo extendiera la vida de la clave, se quedaría fija para siempre.
    assert 0 < r.ttl(key) <= 60

    ss._cache_epoch(r, user.id, 7)          # valor más nuevo
    assert r.get(key) == "7"                # ...sí sube
    assert 60 < r.ttl(key) <= ss._TTL       # ...y esa SÍ republica el TTL


def test_cache_write_fills_an_absent_key(user):
    """La guarda no puede impedir el primer llenado (no hay valor previo)."""
    r = _redis_or_skip()
    key = ss._KEY.format(uid=user.id)
    r.delete(key)

    ss._cache_epoch(r, user.id, 4)

    assert r.get(key) == "4"
    assert 0 < r.ttl(key) <= ss._TTL        # se publica con TTL, no eterno


def test_guard_does_not_block_a_legitimate_raise(user, db_session, patched_session_local):
    """Un bump normal SÍ sube el valor cacheado: la guarda no bloquea lo legítimo."""
    r = _redis_or_skip()
    key = ss._KEY.format(uid=user.id)
    r.delete(key)

    assert ss.current_version(user.id) == 0
    assert r.get(key) == "0"                       # read-through llenó el caché

    ss.bump_version(user.id, db=db_session)        # owns=False → invalida la clave
    db_session.flush()

    assert ss.current_version(user.id) == 1
    assert r.get(key) == "1"                       # el caché SUBIÓ


# ---------------------------------------------------------------------------
# C3: "el usuario no existe" != "no se pudo consultar"
# ---------------------------------------------------------------------------
def test_missing_user_is_zero_not_none(patched_session_local):
    """Fila ausente con la consulta OK → 0, para que un `sv >= 1` siga revocado.

    Devolver None ahí (fail-open) dejaría autenticando hasta su expiración al
    token de un usuario borrado — más laxo que antes de esta tarea.
    """
    ghost = 999999999
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=ghost))
    except Exception:
        pass
    try:
        assert ss._read_epoch_from_db(ghost) == 0
        assert ss.current_version(ghost) == 0
    finally:
        try:
            from itcj2.core.utils.redis_conn import get_redis
            get_redis().delete(ss._KEY.format(uid=ghost))
        except Exception:
            pass


def test_broken_query_is_none_not_zero(monkeypatch):
    """Consulta rota → None (sin información, no revocar). Es el caso contrario."""
    class _DbBoom:
        def execute(self, *a, **k):
            raise ConnectionError("postgres caido")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _DbBoom())
    assert ss._read_epoch_from_db(1234567) is None


def test_failure_to_even_open_a_session_is_none_not_an_exception(monkeypatch):
    """El contrato es `int | None`, nunca una excepción.

    Si `SessionLocal()` mismo lanza (pool agotado, config rota) la excepción se
    escaparía a `current_version` y el `except` del middleware la convertiría en
    una no-revocación silenciosa. Por eso se construye DENTRO del try.
    """
    def _boom():
        raise RuntimeError("no hay pool")

    ghost = 1234567
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=ghost))
    except Exception:
        pass

    monkeypatch.setattr("itcj2.database.SessionLocal", _boom)
    assert ss._read_epoch_from_db(ghost) is None
    # Y el llamador tampoco ve la excepción: MISS en Redis -> BD rota -> None.
    assert ss.current_version(ghost) is None
