"""Handshake WS: revocación por token-version (claim sv), espejo de middleware.py:60-69.

Afecta a TODOS los namespaces (helpdesk, maint, agendatec, /notify, /system)
porque todos autentican vía current_user_from_environ. Las 3 ramas:
  1. sv presente y desactualizado -> rechazado (None)
  2. sv AUSENTE -> pasa aunque haya versión bumpeada (compat; los tokens de
     e2e/global-setup no traen sv)
  3. Redis/servicio caído -> fail-open (pasa)
Usa el Redis real del stack para bump_version. El fixture autouse del conftest
limpia el CACHÉ de authz (roles/perms/has) pero NO las versiones de sesión: barrerlas
desloguearía usuarios reales si la suite corre contra un Redis compartido. Este módulo
limpia sus propios uids al terminar."""
from unittest.mock import patch

from itcj2.core.services import session_service as ss
from itcj2.core.utils import socket_auth
from itcj2.core.utils.jwt_tools import encode_jwt


def _environ(payload: dict) -> dict:
    token = encode_jwt(payload, hours=1)
    return {"HTTP_COOKIE": f"itcj_token={token}"}


def test_sv_vigente_pasa():
    uid = 5661001
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X",
                    "sv": ss.current_version(uid)})
    user = socket_auth.current_user_from_environ(env)
    assert user is not None
    assert user["sub"] == str(uid)


def test_sv_desactualizado_rechazado():
    uid = 5661002
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X",
                    "sv": ss.current_version(uid)})
    ss.bump_version(uid)  # revoca todos los tokens vigentes
    assert socket_auth.current_user_from_environ(env) is None


def test_token_sin_sv_pasa_aunque_haya_version():
    uid = 5661003
    ss.bump_version(uid)  # versión=1, pero el token no trae sv -> no se revisa
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X"})
    assert socket_auth.current_user_from_environ(env) is not None


def test_redis_caido_fail_open():
    uid = 5661004
    env = _environ({"sub": str(uid), "role": "staff", "cn": None, "name": "X", "sv": 99})
    # patch en el MÓDULO FUENTE (socket_auth hace import local dentro de la función)
    with patch(
        "itcj2.core.services.session_service.current_version",
        side_effect=RuntimeError("redis down"),
    ):
        assert socket_auth.current_user_from_environ(env) is not None
