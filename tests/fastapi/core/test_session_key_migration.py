"""Ventana de transición: la clave de versión de sesión cambia de namespace.

De `authz:v1:sessionver:{uid}` (dentro del prefijo del caché, barrible) a
`session:v1:ver:{uid}` (propio). Durante la transición se lee la vieja y se migra
en el sitio, para no desloguear a nadie en el despliegue.
"""
import pytest

from itcj2.core.services import session_service as ss

UID = 5559101


def _redis_or_skip():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        r.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    return r


@pytest.fixture(autouse=True)
def _clean():
    def _rm():
        try:
            from itcj2.core.utils.redis_conn import get_redis
            get_redis().delete(ss._KEY.format(uid=UID), ss._LEGACY_KEY.format(uid=UID))
        except Exception:
            pass
    _rm()
    yield
    _rm()


def test_new_key_is_outside_the_cache_prefix():
    """R4: el dato de sesión no puede vivir bajo `authz:v1:`."""
    assert not ss._KEY.startswith("authz:v1:")


def test_reads_legacy_key_when_new_one_is_absent():
    """R7: desplegar el cambio de prefijo no desloguea a nadie."""
    r = _redis_or_skip()
    r.set(ss._LEGACY_KEY.format(uid=UID), 7)

    assert ss.current_version(UID) == 7


def test_migrates_legacy_key_in_place():
    r = _redis_or_skip()
    r.set(ss._LEGACY_KEY.format(uid=UID), 7)

    ss.current_version(UID)

    assert r.get(ss._KEY.format(uid=UID)) == "7"
    assert r.get(ss._LEGACY_KEY.format(uid=UID)) is None


def test_bump_does_not_lose_the_legacy_value():
    """Sin migrar primero, INCR sobre la clave nueva arrancaría en 1 y bajaría la versión."""
    r = _redis_or_skip()
    r.set(ss._LEGACY_KEY.format(uid=UID), 7)

    assert ss.bump_version(UID) == 8
