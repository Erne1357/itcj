"""
Tests de las páginas de error por app (handler global en itcj2/main.py).

Cubre:
- PageForbidden ahora RENDERIZA página de error 403 (antes redirigía a
  /itcj/dashboard). Botón → panel core (no al inicio de la app).
- Selección de template por prefijo de ruta: maint / helpdesk / core.
- 404 genérico usa el botón "Ir al inicio" de la app.

Estrategia idéntica a test_api_smoke: create_app() real, get_db mockeado,
JWT firmado con SECRET real.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


def _plain_jwt(user_id: int = 777) -> str:
    """JWT autenticado sin role admin (no bypassa autorización)."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": None,
        "cn": None,
        "name": "Plain User",
        "iat": now,
        "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@pytest.fixture
def app_client():
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Cookie": f"itcj_token={_plain_jwt()}"}


# ─────────────────────────────────────────────────────────────────────
# PageForbidden → página de error 403 (NO redirect)
# ─────────────────────────────────────────────────────────────────────

class TestForbiddenRendersErrorPage:
    def test_maint_no_access_renders_403_not_redirect(self, app_client, auth_headers):
        # Sin acceso a la app → require_page_app lanza PageForbidden.
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=False,
        ):
            r = app_client.get(
                "/maint/", headers=auth_headers, follow_redirects=False
            )

        assert r.status_code == 403, f"esperado 403, fue {r.status_code}"
        assert "text/html" in r.headers["content-type"]
        body = r.text
        # Estética maint + botón al panel core (no al inicio de la app).
        assert "Mantenimiento" in body
        assert "Ir al panel principal" in body
        assert "/itcj/dashboard" in body
        # Botón de salida → script que avisa al parent (cierra la ventana).
        assert "CLOSE_APP" in body
        # Ya NO redirige al dashboard.
        assert r.headers.get("location") is None

    def test_has_app_access_but_missing_perm_points_to_app_home(
        self, app_client, auth_headers
    ):
        # Tiene acceso a la app pero le falta el permiso de ESTA página →
        # botón al inicio de la app (sigue en la app), NO al panel core.
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=set(),
        ):
            r = app_client.get(
                "/maint/admin/reports",
                headers=auth_headers,
                follow_redirects=False,
            )

        assert r.status_code == 403
        body = r.text
        assert "Mantenimiento" in body
        assert "Ir al inicio" in body
        assert "Ir al panel principal" not in body
        # No es un botón de salida → sin script CLOSE_APP.
        assert "CLOSE_APP" not in body

    def test_login_required_still_redirects(self, app_client):
        # Sin sesión → PageLoginRequired → sigue redirigiendo a login.
        r = app_client.get("/maint/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"


# ─────────────────────────────────────────────────────────────────────
# Selección de template por prefijo de ruta (404 genérico)
# ─────────────────────────────────────────────────────────────────────

class TestErrorTemplateByApp:
    def test_maint_404_uses_maint_template(self, app_client):
        r = app_client.get("/maint/ruta-inexistente", follow_redirects=False)
        assert r.status_code == 404
        body = r.text
        assert "Mantenimiento" in body
        assert "Ir al inicio" in body
        assert "/maint" in body

    def test_helpdesk_404_uses_helpdesk_template(self, app_client):
        r = app_client.get("/help-desk/ruta-inexistente", follow_redirects=False)
        assert r.status_code == 404
        body = r.text
        assert "Help-Desk" in body
        assert "Ir al inicio" in body
        assert "/help-desk/" in body

    def test_core_404_uses_core_template(self, app_client):
        r = app_client.get("/itcj/ruta-inexistente", follow_redirects=False)
        assert r.status_code == 404
        body = r.text
        assert "404" in body
        assert "No Encontrada" in body
