"""
Tests de acceso a páginas /maint/warehouse/* por rol.

Verifica que el sistema granular de permisos enforces correctamente quién
puede entrar a cada página:
  - admin       → todas (200)
  - dispatcher  → todas excepto categories (302 en categories)
  - tech_maint  → solo dashboard + products (302 en categories/entries/movements)
  - sin perms   → todas redirigen a /itcj/dashboard (302)

Estrategia:
- Mock de `has_any_assignment` y `get_user_permissions_for_app` para inyectar
  el set de perms que tendría cada rol en BD real.
- Mock de `render_maint` para evitar tocar SessionLocal (la nav real abre su
  propia sesión y rompe el aislamiento del test).
- JWT con role=None (no admin bypass) para forzar evaluación de perms.
- `follow_redirects=False` para inspeccionar el 302 directo.
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


# ─── Perms por rol (espejo de database/DML/maint/07_warehouse_pages_granular.sql)
PERMS_BY_ROLE = {
    "admin": {
        "maint.warehouse.page.dashboard",
        "maint.warehouse.page.categories",
        "maint.warehouse.page.products",
        "maint.warehouse.page.entries",
        "maint.warehouse.page.movements",
    },
    "dispatcher": {
        "maint.warehouse.page.dashboard",
        "maint.warehouse.page.products",
        "maint.warehouse.page.entries",
        "maint.warehouse.page.movements",
    },
    "tech_maint": {
        "maint.warehouse.page.dashboard",
        "maint.warehouse.page.products",
    },
    "no_perms": set(),
}

PAGES = [
    ("/maint/warehouse/dashboard",  "maint.warehouse.page.dashboard"),
    ("/maint/warehouse/categories", "maint.warehouse.page.categories"),
    ("/maint/warehouse/products",   "maint.warehouse.page.products"),
    ("/maint/warehouse/entries",    "maint.warehouse.page.entries"),
    ("/maint/warehouse/movements",  "maint.warehouse.page.movements"),
]


def _jwt_for(user_id: int = 100, role: str | None = None) -> str:
    """JWT firmado. role=None evita el bypass admin global de require_perms.

    exp = 24h para evitar que el middleware dispare el refresh JWT,
    el cual abre `SessionLocal()` directo (no respeta dependency_overrides)
    y rompe los tests sin BD.
    """
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
    """TestClient con get_db override, render_maint stubbed, follow_redirects=False."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()

    # Stub de render_maint para no tocar SessionLocal real ni Jinja2
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
        """Cada combinación (rol × página) devuelve 200 si tiene el perm, 302 si no."""
        perms = PERMS_BY_ROLE[role_key]

        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=perms,
        ):
            r = app_client.get(url, headers=_headers(role=None))

        if required_perm in perms:
            assert r.status_code == 200, (
                f"role={role_key} perm={required_perm} presente → esperado 200, fue {r.status_code}"
            )
        else:
            assert r.status_code == 302, (
                f"role={role_key} perm={required_perm} ausente → esperado 302, fue {r.status_code}"
            )
            assert r.headers["location"] == "/itcj/dashboard"

    def test_no_app_assignment_redirects(self, app_client):
        """Sin asignación a maint, todas las páginas redirigen."""
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=False,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=set(),
        ):
            for url, _ in PAGES:
                r = app_client.get(url, headers=_headers(role=None))
                assert r.status_code == 302
                assert r.headers["location"] == "/itcj/dashboard"

    def test_no_auth_redirects_to_login(self, app_client):
        """Sin cookie JWT → redirect a login (no a dashboard)."""
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
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=PERMS_BY_ROLE["tech_maint"],
        ):
            r = app_client.get(url, headers=_headers(role=None))
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/dashboard"

    @pytest.mark.parametrize("url", [
        "/maint/warehouse/dashboard",
        "/maint/warehouse/products",
    ])
    def test_tech_maint_can_access_field_pages(self, app_client, url):
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
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
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=PERMS_BY_ROLE["dispatcher"],
        ):
            r = app_client.get(
                "/maint/warehouse/categories",
                headers=_headers(role=None),
            )
        assert r.status_code == 302

    @pytest.mark.parametrize("url", [
        "/maint/warehouse/dashboard",
        "/maint/warehouse/products",
        "/maint/warehouse/entries",
        "/maint/warehouse/movements",
    ])
    def test_dispatcher_allowed_on_rest(self, app_client, url):
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=PERMS_BY_ROLE["dispatcher"],
        ):
            r = app_client.get(url, headers=_headers(role=None))
        assert r.status_code == 200
