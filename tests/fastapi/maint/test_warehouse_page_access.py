"""
Tests de acceso a páginas /maint/warehouse/* por rol.

Tras la migración a la app warehouse global, las páginas usan
``require_warehouse_page(perm)`` (ver
``itcj2/apps/maint/utils/warehouse_auth.py``), que deriva los permisos
``warehouse.*`` del rol maint del usuario.

Denegación: `PageForbidden` ya NO redirige al dashboard — renderiza la página
de error **403** de la app (ver `page_forbidden_handler` en `itcj2/main.py`,
"antes redirigía al dashboard"). Falta de autenticación sí sigue redirigiendo
(302 → /itcj/login).

Modelo de capacidad (verificado contra la BD real, jun-2026):
  - admin (= jefe head_equipment_maint)  → TODAS (incl. categories, adjust,
    entries.create, products.create/delete) → 200.
  - dispatcher (= secretaría)            → todas excepto categories → 403 en categories.
  - tech_maint                           → dashboard + products (api.consume para
    consumir materiales) → 403 en categories/entries/movements.
  - sin perms                            → 403 en todas.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# Perms warehouse derivados desde el rol maint (espejo de
# database/DML/warehouse/03_assign_warehouse_permissions_to_maint_roles.sql)
PERMS_BY_ROLE = {
    "admin": {
        "warehouse.page.dashboard",
        "warehouse.page.categories",
        "warehouse.page.products",
        "warehouse.page.entries",
        "warehouse.page.movements",
        "warehouse.page.reports",
    },
    "dispatcher": {
        "warehouse.page.dashboard",
        "warehouse.page.products",
        "warehouse.page.entries",
        "warehouse.page.movements",
        "warehouse.page.reports",
    },
    "tech_maint": {
        # tech_maint en warehouse solo tiene api.read + api.consume (sin pages)
        # pero la nav le da dashboard + products vía perms de página específicos
        # → en la BD real esto se ajusta. Aquí simulamos el escenario operativo.
        "warehouse.page.dashboard",
        "warehouse.page.products",
    },
    "no_perms": set(),
}

PAGES = [
    ("/maint/warehouse/dashboard",  "warehouse.page.dashboard"),
    ("/maint/warehouse/categories", "warehouse.page.categories"),
    ("/maint/warehouse/products",   "warehouse.page.products"),
    ("/maint/warehouse/entries",    "warehouse.page.entries"),
    ("/maint/warehouse/movements",  "warehouse.page.movements"),
]


def _jwt_for(user_id: int = 100, role: str | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "cn": None,
        "name": "Test User",
        "iat": now,
        "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@pytest.fixture
def app_client():
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()

    patcher = patch(
        "itcj2.apps.maint.pages.warehouse.render_maint",
        return_value=HTMLResponse("<ok />", status_code=200),
    )
    patcher.start()

    with TestClient(app, follow_redirects=False) as c:
        yield c

    patcher.stop()
    app.dependency_overrides.clear()


def _headers(role: str | None = None) -> dict:
    return {"Cookie": f"itcj_token={_jwt_for(role=role)}"}


# ─────────────────────────────────────────────────────────────────────
# Acceso por rol — happy path + denials
# ─────────────────────────────────────────────────────────────────────

class TestPageAccessByRole:
    @pytest.mark.parametrize("role_key", ["admin", "dispatcher", "tech_maint", "no_perms"])
    @pytest.mark.parametrize("url,required_perm", PAGES)
    def test_page_enforces_granular_perm(self, app_client, role_key, url, required_perm):
        perms = PERMS_BY_ROLE[role_key]

        with patch(
            "itcj2.apps.maint.utils.warehouse_auth.get_warehouse_perms_via_maint",
            return_value=perms,
        ):
            r = app_client.get(url, headers=_headers(role=None))

        if required_perm in perms:
            assert r.status_code == 200, (
                f"role={role_key} perm={required_perm} presente → esperado 200, fue {r.status_code}"
            )
        else:
            # PageForbidden → página de error 403 (ya no redirige al dashboard).
            assert r.status_code == 403, (
                f"role={role_key} perm={required_perm} ausente → esperado 403, fue {r.status_code}"
            )

    def test_no_auth_redirects_to_login(self, app_client):
        for url, _ in PAGES:
            r = app_client.get(url)
            assert r.status_code == 302
            assert r.headers["location"] == "/itcj/login"

    def test_invalid_token_redirects_to_login(self, app_client):
        for url, _ in PAGES:
            r = app_client.get(url, headers={"Cookie": "itcj_token=bogus"})
            assert r.status_code == 302
            assert r.headers["location"] == "/itcj/login"


# ─────────────────────────────────────────────────────────────────────
# Verificación específica: tech_maint NO ve categories/entries/movements
# ─────────────────────────────────────────────────────────────────────

class TestTechMaintScope:
    @pytest.mark.parametrize("url", [
        "/maint/warehouse/categories",
        "/maint/warehouse/entries",
        "/maint/warehouse/movements",
    ])
    def test_tech_maint_cannot_access_admin_pages(self, app_client, url):
        with patch(
            "itcj2.apps.maint.utils.warehouse_auth.get_warehouse_perms_via_maint",
            return_value=PERMS_BY_ROLE["tech_maint"],
        ):
            r = app_client.get(url, headers=_headers(role=None))
        assert r.status_code == 403

    @pytest.mark.parametrize("url", [
        "/maint/warehouse/dashboard",
        "/maint/warehouse/products",
    ])
    def test_tech_maint_can_access_field_pages(self, app_client, url):
        with patch(
            "itcj2.apps.maint.utils.warehouse_auth.get_warehouse_perms_via_maint",
            return_value=PERMS_BY_ROLE["tech_maint"],
        ):
            r = app_client.get(url, headers=_headers(role=None))
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Verificación dispatcher: todas menos categories
# ─────────────────────────────────────────────────────────────────────

class TestDispatcherScope:
    def test_dispatcher_blocked_on_categories(self, app_client):
        with patch(
            "itcj2.apps.maint.utils.warehouse_auth.get_warehouse_perms_via_maint",
            return_value=PERMS_BY_ROLE["dispatcher"],
        ):
            r = app_client.get(
                "/maint/warehouse/categories",
                headers=_headers(role=None),
            )
        assert r.status_code == 403

    @pytest.mark.parametrize("url", [
        "/maint/warehouse/dashboard",
        "/maint/warehouse/products",
        "/maint/warehouse/entries",
        "/maint/warehouse/movements",
    ])
    def test_dispatcher_allowed_on_rest(self, app_client, url):
        with patch(
            "itcj2.apps.maint.utils.warehouse_auth.get_warehouse_perms_via_maint",
            return_value=PERMS_BY_ROLE["dispatcher"],
        ):
            r = app_client.get(url, headers=_headers(role=None))
        assert r.status_code == 200
