"""Handshake WS: revocación por token-version (claim sv), espejo de middleware.py:60-69.

Afecta a TODOS los namespaces (helpdesk, maint, agendatec, /notify, /system)
porque todos autentican vía current_user_from_environ. Las 4 ramas:
  1. sv presente y desactualizado -> rechazado (None)
  2. sv AUSENTE -> pasa aunque haya versión bumpeada (compat; los tokens de
     e2e/global-setup no traen sv)
  3. current_version() lanza una excepción cruda -> el try/except de
     current_user_from_environ ya la perdonaba ANTES de la Tarea 4 (fail-open
     "por accidente"; no ejercita el guard `cur is not None`)
  4. current_version() devuelve None explícitamente (Redis inalcanzable, sin
     excepción) -> fail-open real, es el guard `cur is not None` agregado en la
     Tarea 4 (socket_auth.py:28-29)

Desde la Tarea 5 la época vive en `core_users.session_epoch` y Redis solo la
cachea, así que `bump_version` sobre un uid FICTICIO no hace nada: el
`UPDATE ... WHERE id = :uid` no encuentra fila, devuelve None y no toca Redis.
Las ramas 1-3 usan por eso un usuario REAL (fixture `user`) y pasan la sesión
del test (`db=db_session`). Las ramas 4-5 parchean `current_version` entero, así
que nunca llegan ni a Postgres ni a Redis y pueden seguir con uids ficticios.

El fixture autouse del conftest limpia el CACHÉ de authz (roles/perms/has) pero NO
las épocas de sesión: barrerlas desloguearía usuarios reales si la suite corre
contra un Redis compartido. Este módulo limpia sus propios uids al terminar."""
from unittest.mock import patch

import pytest

from itcj2.core.models.user import User
from itcj2.core.services import session_service as ss
from itcj2.core.utils import socket_auth
from itcj2.core.utils.jwt_tools import encode_jwt

# uids ficticios de las ramas que parchean current_version (no tocan BD ni Redis)
_GHOST_UIDS = (5661004, 5661005)


def _drop_keys(*uids):
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        for u in uids:
            r.delete(ss._KEY.format(uid=u))
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean_ghost_keys():
    """Cumple la promesa del docstring: el módulo limpia SUS uids, no un glob."""
    _drop_keys(*_GHOST_UIDS)
    yield
    _drop_keys(*_GHOST_UIDS)


@pytest.fixture()
def user(db_session):
    """Usuario real: `bump_version` necesita una fila para poder incrementar."""
    u = User(first_name="Socket", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    yield u
    try:
        _drop_keys(u.id)
    except Exception:
        pass


def _environ(payload: dict) -> dict:
    token = encode_jwt(payload, hours=1)
    return {"HTTP_COOKIE": f"itcj_token={token}"}


def test_sv_vigente_pasa(user, patched_session_local):
    env = _environ({"sub": str(user.id), "role": "staff", "cn": None, "name": "X",
                    "sv": ss.current_version(user.id)})
    result = socket_auth.current_user_from_environ(env)
    assert result is not None
    assert result["sub"] == str(user.id)


def test_sv_desactualizado_rechazado(user, db_session, patched_session_local):
    env = _environ({"sub": str(user.id), "role": "staff", "cn": None, "name": "X",
                    "sv": ss.current_version(user.id)})
    assert ss.bump_version(user.id, db=db_session) == 1   # revoca los tokens vigentes
    db_session.flush()

    assert socket_auth.current_user_from_environ(env) is None


def test_token_sin_sv_pasa_aunque_haya_version(user, db_session, patched_session_local):
    assert ss.bump_version(user.id, db=db_session) == 1
    db_session.flush()
    assert ss.current_version(user.id) == 1   # la época SÍ está bumpeada...

    env = _environ({"sub": str(user.id), "role": "staff", "cn": None, "name": "X"})

    # ...pero el token no trae sv, así que no se revisa (compat hacia atrás).
    assert socket_auth.current_user_from_environ(env) is not None


def test_redis_caido_fail_open():
    """current_version() lanza una excepción cruda. El try/except de
    current_user_from_environ ya perdonaba esto ANTES de la Tarea 4 — esta
    rama NO ejercita el guard `cur is not None` agregado por esa tarea. Se
    conserva porque sigue siendo un caso de fail-open real (aunque por una
    ruta distinta), no porque cubra el cambio de esa tarea.
    """
    uid = 5661004
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X", "sv": 99})
    # patch en el MÓDULO FUENTE (socket_auth hace import local dentro de la función)
    with patch(
        "itcj2.core.services.session_service.current_version",
        side_effect=RuntimeError("redis down"),
    ):
        assert socket_auth.current_user_from_environ(env) is not None


def test_current_version_none_fail_open():
    """R5: current_version() devuelve None explícitamente (Redis inalcanzable,
    sin lanzar) -> NO revoca. Este es el guard nuevo `cur is not None` en
    socket_auth.py:28-29 (Tarea 4). A diferencia de test_redis_caido_fail_open,
    esta rama SÍ falla contra el código previo a la Tarea 4: ahí la comparación
    era `int(data.get("sv", 0)) != current_version(...)`, es decir
    `99 != None` -> True -> revocado (retorna None).
    """
    uid = 5661005
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X", "sv": 99})
    with patch(
        "itcj2.core.services.session_service.current_version",
        return_value=None,
    ):
        user = socket_auth.current_user_from_environ(env)
    assert user is not None
    assert user["sub"] == str(uid)
