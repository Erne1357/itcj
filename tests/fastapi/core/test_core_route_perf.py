"""Rutas de core que salían lentas en prod (perf 2026-10-07).

- `GET /api/core/v2/user/password-state` verificaba la contraseña por omisión
  contra el hash con scrypt (~100 ms y ~32 MB) en CADA llamada; el resultado
  solo depende del hash, así que se calcula una vez por hash.
- La app se buscaba por `key` en cada `user_roles_in_app` (dos veces: la otra
  dentro de `user_roles_via_positions`); `/user/me` y `/itcj/m/` lo hacían por
  cada app. Ahora la sesión recuerda las apps activas.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import event

from tests.conftest import FakeUser


# ---------------------------------------------------------------------------
# password-state: una verificación por hash
# ---------------------------------------------------------------------------
class _ContarVerify:
    def __init__(self, resultado: bool):
        self.resultado = resultado
        self.llamadas = 0

    def __call__(self, nip, nip_hash):
        self.llamadas += 1
        return self.resultado


def _estado(app_client, auth_headers, user):
    with patch("itcj2.core.api.users._get_user", return_value=user):
        resp = app_client.get("/api/core/v2/user/password-state", headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["must_change"]


@patch("itcj2.core.services.authz_service.user_roles_in_app", return_value={"admin"})
def test_el_mismo_hash_no_se_vuelve_a_verificar(_roles, app_client, auth_headers):
    verify = _ContarVerify(True)
    user = FakeUser(id=200, password_hash="hash-perf-1")
    with patch("itcj2.core.utils.security.verify_nip", verify):
        assert _estado(app_client, auth_headers, user) is True
        assert _estado(app_client, auth_headers, user) is True
    assert verify.llamadas == 1, "scrypt una sola vez por hash"


@patch("itcj2.core.services.authz_service.user_roles_in_app", return_value={"admin"})
def test_un_hash_distinto_se_verifica_aparte(_roles, app_client, auth_headers):
    with patch("itcj2.core.utils.security.verify_nip", _ContarVerify(True)):
        assert _estado(app_client, auth_headers,
                       FakeUser(id=200, password_hash="hash-perf-2")) is True
    verify = _ContarVerify(False)
    with patch("itcj2.core.utils.security.verify_nip", verify):
        assert _estado(app_client, auth_headers,
                       FakeUser(id=200, password_hash="hash-perf-3")) is False
    assert verify.llamadas == 1


@patch("itcj2.core.services.authz_service.user_roles_in_app", return_value={"admin"})
def test_cambiar_la_contrasena_cambia_el_resultado(_roles, app_client, auth_headers):
    """Con hashes reales: el de la contraseña por omisión da True; al cambiarla
    el hash es otro y el estado se recalcula (sin invalidar nada a mano)."""
    from itcj2.core.utils.security import DEFAULT_PASSWORD, hash_nip

    user = FakeUser(id=201, password_hash=hash_nip(DEFAULT_PASSWORD))
    assert _estado(app_client, auth_headers, user) is True
    user.password_hash = hash_nip("otra-contrasena-1")
    assert _estado(app_client, auth_headers, user) is False


def test_el_resultado_no_guarda_la_contrasena():
    """La caché se indexa por el hash (que ya vive en la BD), nunca por texto plano."""
    from itcj2.core.utils import security

    security.is_default_password_hash.cache_clear()
    security.is_default_password_hash("hash-perf-4")
    assert security.is_default_password_hash.cache_info().currsize == 1


# ---------------------------------------------------------------------------
# Apps por key: una consulta por sesión, no una por llamada
# ---------------------------------------------------------------------------
@pytest.fixture()
def contar_sql(db_session):
    sentencias = []

    def _antes(conn, cursor, statement, params, context, executemany):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _antes)
    yield sentencias
    event.remove(conn, "before_cursor_execute", _antes)


def _de_apps(sentencias):
    return [s for s in sentencias if "FROM core_apps" in s]


def _app(db, key, **kw):
    """App propia de la prueba: la base de CI no trae ninguna (sin DML)."""
    from itcj2.core.models.app import App

    app = App(key=key, name=key, is_active=True, **kw)
    db.add(app)
    db.flush()
    return app


def test_buscar_la_misma_app_varias_veces_consulta_una(db_session, contar_sql):
    from itcj2.core.services.authz_service import get_or_404_app

    _app(db_session, "perf-a")
    contar_sql.clear()
    a = get_or_404_app(db_session, "perf-a")
    b = get_or_404_app(db_session, "perf-a")
    c = get_or_404_app(db_session, "perf-a")

    assert a is b is c and a.key == "perf-a"
    assert len(_de_apps(contar_sql)) <= 1


def test_una_app_desactivada_en_la_sesion_deja_de_encontrarse(db_session):
    from fastapi import HTTPException

    from itcj2.core.services.authz_service import get_app_by_key, get_or_404_app

    app = _app(db_session, "perf-b")
    assert get_or_404_app(db_session, "perf-b") is app
    app.is_active = False
    db_session.flush()

    assert get_app_by_key(db_session, "perf-b") is None
    with pytest.raises(HTTPException):
        get_or_404_app(db_session, "perf-b")


def test_una_app_creada_y_deshecha_por_rollback_no_se_recuerda(db_session):
    """Alta dentro de un savepoint que se deshace: la memoria no la devuelve."""
    from itcj2.core.services.authz_service import get_app_by_key

    _app(db_session, "perf-c")
    get_app_by_key(db_session, "perf-c")              # carga la memoria
    sp = db_session.begin_nested()
    _app(db_session, "perf-efimera")
    assert get_app_by_key(db_session, "perf-efimera") is not None
    sp.rollback()

    assert get_app_by_key(db_session, "perf-efimera") is None


def test_una_app_que_no_existe_sigue_dando_none(db_session):
    from itcj2.core.services.authz_service import get_app_by_key

    assert get_app_by_key(db_session, "no-existe-perf") is None


def test_roles_de_varias_apps_sin_buscar_cada_app(db_session, contar_sql):
    """`/user/me` pide los roles de cada app: la app ya no se busca por llamada
    (antes 2 consultas a core_apps por app)."""
    from itcj2.core.services.authz_service import user_roles_in_app

    keys = ["perf-r1", "perf-r2", "perf-r3"]
    for key in keys:
        _app(db_session, key)
    db_session.info.pop("itcj2.core.active_apps_by_key", None)
    contar_sql.clear()
    for key in keys:
        user_roles_in_app(db_session, 1, key)

    assert len(_de_apps(contar_sql)) <= 1
    assert len(contar_sql) <= 1 + 2 * len(keys)


def _redis_vivo() -> bool:
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return bool(get_redis().ping())
    except Exception:
        return False


def test_el_shell_movil_no_recalcula_roles_con_el_cache_caliente(db_session, contar_sql):
    """`/itcj/m/` (`get_mobile_apps_for_user`): asignación y roles por app salen
    del caché de authz; la segunda carga no toca las tablas de roles."""
    if not _redis_vivo():
        pytest.skip("sin Redis el caché de authz cae a la BD (fail-open)")
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.services.mobile_service import get_mobile_apps_for_user

    app = _app(db_session, "perf-movil", mobile_enabled=True)
    rol = db_session.query(Role).filter_by(name="perf-rol").first() or Role(name="perf-rol")
    db_session.add(rol)
    user = User(username="perf.movil", first_name="PERF", last_name="MOVIL")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=rol.id))
    db_session.flush()

    primera = get_mobile_apps_for_user(db_session, user.id)
    contar_sql.clear()
    segunda = get_mobile_apps_for_user(db_session, user.id)

    assert [a["key"] for a in primera] == [a["key"] for a in segunda] == ["perf-movil"]
    assert segunda[0]["user_roles"] == ["perf-rol"]
    roles_sql = [s for s in contar_sql if "core_user_app_roles" in s or "core_position_app_roles" in s]
    assert roles_sql == [], "con el caché caliente no se consultan roles"
