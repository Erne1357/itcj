"""Acceso a las vistas de Ayuda de maint por rol/permiso.

Regla: solo el rol ADMIN de la app maint (incluye al jefe de mantenimiento,
admin vía su puesto) ve las 3 vistas. Ser admin GLOBAL del sistema NO basta —
un jefe de otro departamento (department_head) solo ve la guía de solicitante.
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


def _jwt(user_id=10, role=None):
    s = get_settings()
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "role": role, "cn": None, "name": "T", "iat": now, "exp": now + 3600},
        s.SECRET_KEY, algorithm="HS256",
    )


def _headers(role=None):
    return {"Cookie": f"itcj_token={_jwt(role=role)}"}


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    # render_maint se mockea para no tocar plantillas/sesión Jinja.
    p = patch("itcj2.apps.maint.pages.help.render_maint",
              return_value=HTMLResponse("<ok/>", status_code=200))
    p.start()
    with TestClient(app, follow_redirects=False) as c:
        yield c
    p.stop()
    app.dependency_overrides.clear()


def _patch_authz(roles, perms):
    """Parcha las 3 funciones authz que usa _resolve_help_access."""
    return (
        patch("itcj2.core.services.authz_service.has_any_assignment", return_value=True),
        patch("itcj2.core.services.authz_service.user_roles_in_app", return_value=roles),
        patch("itcj2.core.services.authz_service.get_user_permissions_for_app", return_value=set(perms)),
    )


class TestHelpAccess:
    def test_global_admin_dept_head_only_requester(self, client):
        """BUG FIX: admin GLOBAL del sistema + department_head en maint (sin rol
        admin de maint) → /help/admin y /help/tech redirigen a /help."""
        a, b, c = _patch_authz(["department_head"], ["maint.help.page.requester"])
        with a, b, c:
            r_req = client.get("/maint/help", headers=_headers(role="admin"))
            r_adm = client.get("/maint/help/admin", headers=_headers(role="admin"))
            r_tec = client.get("/maint/help/tech", headers=_headers(role="admin"))
        assert r_req.status_code == 200
        assert r_adm.status_code == 302 and r_adm.headers["location"] == "/maint/help"
        assert r_tec.status_code == 302 and r_tec.headers["location"] == "/maint/help"

    def test_maint_admin_sees_all(self, client):
        """Rol admin DE LA APP maint (jefe de mantenimiento) ve las 3 vistas."""
        a, b, c = _patch_authz(["admin", "department_head"], ["maint.help.page.requester"])
        with a, b, c:
            assert client.get("/maint/help", headers=_headers()).status_code == 200
            assert client.get("/maint/help/admin", headers=_headers()).status_code == 200
            assert client.get("/maint/help/tech", headers=_headers()).status_code == 200

    def test_tech_only_sees_tech(self, client):
        """tech_maint (sin perm requester) aterriza en /help/tech; /help redirige."""
        a, b, c = _patch_authz(["tech_maint"], ["maint.help.page.tech"])
        with a, b, c:
            r_req = client.get("/maint/help", headers=_headers())
            r_tec = client.get("/maint/help/tech", headers=_headers())
        assert r_tec.status_code == 200
        assert r_req.status_code == 302 and r_req.headers["location"] == "/maint/help/tech"
