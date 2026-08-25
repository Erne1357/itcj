"""Tests HTTP de ``itcj2.apps.adhoc.api.mail`` y ``...api.users``.

Los routers ya están cableados en ``itcj2/apps/adhoc/router.py``, así que el
fixture NO los monta: usa las rutas reales de la app
(``/api/adhoc/v2/mail-config`` y ``/api/adhoc/v2/users``). Montarlos otra vez
duplicaría el árbol y haría que estos tests pasaran aunque el cableado
estuviera mal.

Lo que estos tests protegen, en una línea: que la pantalla más peligrosa del
legacy —usuarios, anónima, con ``role_id=4`` hardcodeado— quede reducida a tres
rutas con permiso, y que el ``GET`` de correo no vuelva a escribir en la BD.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from itcj2.database import get_db
from tests.conftest import make_jwt

MAIL_SVC = "itcj2.apps.adhoc.services.user_admin_service.MailConfigService"
USER_SVC = "itcj2.apps.adhoc.services.user_admin_service.UserAdminService"

BASE = "/api/adhoc/v2"
MAIL = f"{BASE}/mail-config"
USERS = f"{BASE}/users"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(app_client):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield app_client
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


def _admin():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


def _staff():
    return {"Cookie": f"itcj_token={make_jwt(user_id=300, role='staff')}"}


def _fake_cfg(is_enabled=True):
    return SimpleNamespace(id=1, is_enabled=is_enabled, updated_at=datetime(2026, 8, 25, 10, 0))


def _fake_user_row(user_id=42):
    return {
        "id": user_id,
        "username": "jperez",
        "control_number": None,
        "email": "jperez@cdjuarez.tecnm.mx",
        "first_name": "JUAN",
        "last_name": "PEREZ",
        "middle_name": "LOPEZ",
        "full_name": "PEREZ LOPEZ JUAN",
        "is_active": True,
        "roles": ["supervisor_doc"],
        "areas": [{"id": 3, "name": "Calidad", "color": "#4834d4", "is_active": True}],
    }


ROUTES = [
    ("get", MAIL, None),
    ("put", MAIL, {"json": {"is_enabled": True}}),
    ("get", USERS, None),
    ("put", f"{USERS}/42/app-role", {"json": {"role": "consult"}}),
    ("put", f"{USERS}/42/areas", {"json": {"area_ids": [1]}}),
]


# ---------------------------------------------------------------------------
# Autenticación y autorización
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,url,kwargs", ROUTES)
def test_every_route_rejects_anonymous(client, method, url, kwargs):
    """En el legacy las 4 rutas equivalentes eran **anónimas**: cualquiera podía
    apagar el correo del SGC o darse de alta como admin."""
    resp = getattr(client, method)(url, **(kwargs or {}))
    assert resp.status_code == 401
    assert isinstance(resp.json()["error"], str)


@pytest.mark.parametrize("method,url,kwargs", ROUTES)
def test_every_route_rejects_missing_permission(client, method, url, kwargs):
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set()):
        resp = getattr(client, method)(url, headers=_staff(), **(kwargs or {}))
    assert resp.status_code == 403


@pytest.mark.parametrize("url,perm,target", [
    (MAIL, "adhoc.mail.api.read", f"{MAIL_SVC}.get"),
    (USERS, "adhoc.users.api.read", f"{USER_SVC}.list_users"),
])
def test_exact_dml_permission_opens_the_route(client, url, perm, target):
    """Los códigos son los de ``database/DML/adhoc/init/02_insert_permissions.sql``."""
    return_value = _fake_cfg() if url == MAIL else []
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value={perm}), \
         patch(target, return_value=return_value):
        resp = client.get(url, headers=_staff())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /mail-config
# ---------------------------------------------------------------------------

def test_get_mail_config_returns_the_flag(client):
    with patch(f"{MAIL_SVC}.get", return_value=_fake_cfg(True)):
        resp = client.get(MAIL, headers=_admin())

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["is_enabled"] is True
    assert body["data"]["updated_at"].startswith("2026-08-25")


def test_get_mail_config_never_writes(client):
    """Regresión: el legacy hacía ``add()`` + ``commit()`` dentro del GET."""
    with patch(f"{MAIL_SVC}.get", return_value=_fake_cfg()) as get_mock, \
         patch(f"{MAIL_SVC}.set_enabled") as write_mock:
        resp = client.get(MAIL, headers=_admin())

    assert resp.status_code == 200
    get_mock.assert_called_once()
    write_mock.assert_not_called()


def test_get_mail_config_without_the_seeded_row_is_503(client):
    """Que falte la fila singleton significa despliegue incompleto, no 'creala
    al vuelo'."""
    with patch(f"{MAIL_SVC}.get", return_value=None):
        resp = client.get(MAIL, headers=_admin())

    assert resp.status_code == 503
    assert "05_seed_catalogs.sql" in resp.json()["error"]


def test_put_mail_config_toggles_the_flag(client):
    with patch(f"{MAIL_SVC}.set_enabled", return_value=_fake_cfg(False)) as mock:
        resp = client.put(MAIL, headers=_admin(), json={"is_enabled": False})

    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is False
    assert mock.call_args.args[1] is False


def test_put_mail_config_requires_the_flag(client):
    resp = client.put(MAIL, headers=_admin(), json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /users
# ---------------------------------------------------------------------------

def test_list_users_returns_roles_and_areas(client):
    with patch(f"{USER_SVC}.list_users", return_value=[_fake_user_row()]):
        resp = client.get(USERS, headers=_admin())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["data"][0]
    assert row["roles"] == ["supervisor_doc"]
    assert row["areas"][0]["name"] == "Calidad"
    assert row["full_name"] == "PEREZ LOPEZ JUAN"


def test_list_users_without_the_app_registered_is_404(client):
    with patch(f"{USER_SVC}.list_users",
               side_effect=LookupError("La aplicacion 'adhoc' no esta registrada")):
        resp = client.get(USERS, headers=_admin())
    assert resp.status_code == 404


def test_set_app_role_ok(client):
    with patch(f"{USER_SVC}.set_app_role", return_value={"user_id": 42, "role": "consult"}) as mock:
        resp = client.put(f"{USERS}/42/app-role", headers=_admin(), json={"role": "consult"})

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert mock.call_args.args[1:3] == (42, "consult")


@pytest.mark.parametrize("role", ["admin", "consult", "supervisor_doc",
                                  "supervisor_inc", "supervisor_prog"])
def test_set_app_role_accepts_the_five_app_roles(client, role):
    """Los 5 de ``01_insert_roles.sql`` + el ``admin`` global del core."""
    with patch(f"{USER_SVC}.set_app_role", return_value={"user_id": 42, "role": role}):
        resp = client.put(f"{USERS}/42/app-role", headers=_admin(), json={"role": role})
    assert resp.status_code == 200


def test_set_app_role_rejects_a_role_outside_the_app(client):
    """``student`` daría acceso a la app con cero permisos: 403 en las 26
    páginas."""
    resp = client.put(f"{USERS}/42/app-role", headers=_admin(), json={"role": "student"})
    assert resp.status_code == 422


def test_set_app_role_unknown_user_is_404(client):
    with patch(f"{USER_SVC}.set_app_role", side_effect=LookupError("El usuario 42 no existe")):
        resp = client.put(f"{USERS}/42/app-role", headers=_admin(), json={"role": "consult"})
    assert resp.status_code == 404
    assert resp.json() == {"error": "El usuario 42 no existe", "status": 404}


def test_set_areas_ok(client):
    with patch(f"{USER_SVC}.set_areas",
               return_value={"user_id": 42, "area_ids": [1, 3]}) as mock:
        resp = client.put(f"{USERS}/42/areas", headers=_admin(), json={"area_ids": [1, 3, 3]})

    assert resp.status_code == 200
    # El schema deduplica antes de llegar al service.
    assert mock.call_args.args[1:3] == (42, [1, 3])


def test_set_areas_accepts_an_empty_list(client):
    with patch(f"{USER_SVC}.set_areas", return_value={"user_id": 42, "area_ids": []}) as mock:
        resp = client.put(f"{USERS}/42/areas", headers=_admin(), json={"area_ids": []})

    assert resp.status_code == 200
    assert mock.call_args.args[2] == []


def test_set_areas_rejects_a_non_numeric_id(client):
    resp = client.put(f"{USERS}/42/areas", headers=_admin(), json={"area_ids": ["ñ"]})
    assert resp.status_code == 422


def test_set_areas_unknown_area_is_400(client):
    with patch(f"{USER_SVC}.set_areas",
               side_effect=ValueError("Area(s) inexistente(s): 99")):
        resp = client.put(f"{USERS}/42/areas", headers=_admin(), json={"area_ids": [99]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Area(s) inexistente(s): 99"


def test_set_areas_for_a_user_outside_the_app_is_400(client):
    with patch(f"{USER_SVC}.set_areas",
               side_effect=ValueError("El usuario no tiene acceso a Calidad")):
        resp = client.put(f"{USERS}/42/areas", headers=_admin(), json={"area_ids": [1]})
    assert resp.status_code == 400


def test_user_creation_and_password_change_are_not_ported(client):
    """D8: el alta de personas y el cambio de contraseña se quedan en el core.

    Las rutas del legacy (``POST /usuarios/save``, ``POST /usuarios/edit/<id>``)
    no existen aquí, y ``POST /users`` tampoco: el router solo declara GET y
    dos PUT.
    """
    # 405 cuando la URL existe con otro método (``GET /users``), 404 cuando no
    # existe ninguna ruta con esa forma (``/users/{id}`` a secas).
    assert client.post(USERS, headers=_admin(), json={}).status_code == 405
    assert client.delete(f"{USERS}/42", headers=_admin()).status_code in (404, 405)
    assert client.post(f"{USERS}/42/password", headers=_admin(), json={}).status_code == 404
