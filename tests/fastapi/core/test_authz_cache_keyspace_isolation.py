"""Regresión: el caché de authz y la revocación de sesión NO comparten keyspace.

Bug (2026-08-20): `invalidate_all()` barría el glob `authz:v1:*`, que incluía
`authz:v1:sessionver:{uid}` — la clave de sesión de entonces — y deslogueaba a
TODOS los usuarios al cambiar UN permiso de UN rol. Hoy la época de sesión
canónica es `session:v1:ver:{uid}`, fuera de ese prefijo, y su fuente de verdad
es `core_users.session_epoch`; el glob sigue prohibido igual, porque cualquier
vecino futuro bajo `authz:v1:` sería igual de vulnerable.
Ver docs/superpowers/specs/2026-08-20-authz-cache-keyspace-collision.md

Estos tests exigen Redis vivo: sin Redis los wrappers son fail-open y no hay
keyspace que aislar, así que se skipean.
"""
import pytest

from itcj2.core.services import authz_cache as ac
from itcj2.core.services import session_service as ss


def _redis_or_skip():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        r.ping()
    except Exception:
        pytest.skip("Redis no disponible; el aislamiento de keyspace no aplica")
    return r


@pytest.fixture()
def uid():
    """UID de prueba aislado que limpia SU clave de sesión al terminar.

    Se usa `ss._KEY` (privado) a propósito: así el test sigue apuntando a la clave
    correcta cuando la Tarea 3 mueva el prefijo. Y no se flushea un glob de sesión
    desde el conftest — eso es justo el segundo vector del bug (ver Tarea 2).
    """
    u = 5559001
    yield u
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete(ss._KEY.format(uid=u))
    except Exception:
        pass


def test_new_key_is_outside_the_cache_prefix():
    """R4: el dato de revocación NO puede vivir bajo el prefijo del caché.

    Guarda estructural de una línea: si alguien devolviera `_KEY` a `authz:v1:`,
    `invalidate_all()` volvería a barrerlo y el incidente se repetiría. Vivía en
    test_session_key_migration.py, borrado en la Tarea 5 junto con la ventana de
    transición; la aserción sigue vigente y su sitio natural es este módulo.
    """
    assert not ss._KEY.startswith("authz:v1:")


def test_invalidate_all_preserves_session_version(uid):
    """R1: cambiar permisos de un rol NO puede desloguear a nadie.

    Se siembra y se comprueba la CLAVE de Redis directamente, no vía
    bump_version/current_version: el uid es ficticio y a partir de la Tarea 5 esas
    funciones exigen una fila real en core_users. Lo que este test pinnea es
    exactamente el contrato de keyspace — `invalidate_all` no toca esa clave.
    """
    r = _redis_or_skip()
    # OJO: sembrar DENTRO del test. El fixture autouse de tests/fastapi/conftest.py
    # flushea antes de cada test, así que sembrar fuera del cuerpo no sirve de nada.
    r.set(ss._KEY.format(uid=uid), 7)

    ac.invalidate_all()

    assert r.get(ss._KEY.format(uid=uid)) == "7"


def test_invalidate_all_still_clears_authz_cache(uid):
    """R2: no vaciar de contenido la invalidación al estrecharla."""
    r = _redis_or_skip()
    r.setex(ac._key("perms", "helpdesk", uid), 300, '["helpdesk.x"]')
    r.setex(ac._key("roles", "helpdesk", uid), 300, '["admin"]')
    r.setex(ac._key("has", "helpdesk", uid), 300, "true")
    r.setex(ac._DEPTMAP_KEY, 300, '{"1": [1]}')

    ac.invalidate_all()

    assert r.get(ac._key("perms", "helpdesk", uid)) is None
    assert r.get(ac._key("roles", "helpdesk", uid)) is None
    assert r.get(ac._key("has", "helpdesk", uid)) is None
    assert r.get(ac._DEPTMAP_KEY) is None


def test_invalidate_user_preserves_session_version(uid):
    """Pinnea el contrato de `invalidate_user`: hoy es seguro por accidente."""
    r = _redis_or_skip()
    r.set(ss._KEY.format(uid=uid), 7)

    ac.invalidate_user(uid)

    assert r.get(ss._KEY.format(uid=uid)) == "7"


def test_suite_fixture_does_not_wipe_session_versions(uid):
    """R3: correr la suite contra un Redis compartido no debe desloguear a nadie.

    Ejercita el mismo `_flush()` que el fixture autouse de tests/fastapi/conftest.py
    corre antes y después de CADA test.
    """
    r = _redis_or_skip()
    r.set(ss._KEY.format(uid=uid), 7)

    from tests.fastapi.conftest import _flush_authz_cache
    _flush_authz_cache()

    assert r.get(ss._KEY.format(uid=uid)) == "7"
