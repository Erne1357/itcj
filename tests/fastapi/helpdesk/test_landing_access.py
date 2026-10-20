"""
Acceso al landing de Help-Desk (`GET /help-desk/`).

Antes el landing usaba `require_page_login`: cualquier usuario con sesión lo veía
aunque no tuviera ninguna asignación en la app. Ahora usa
`require_page_app("helpdesk")` (mismo patrón que `maint/pages/landing.py`), así
que quien no tiene acceso ve el 403 verde de Help-Desk con el botón al panel
principal (el handler global de `itcj2/main.py` pinta la página).

El POST de la misma ruta («Pedir ayuda», JSON `no_roles`) NO cambia: se cubre
aquí para que el cambio del GET no lo arrastre.

Estrategia idéntica a `tests/fastapi/maint/test_error_pages.py`: create_app()
real, get_db mockeado, JWT firmado con el SECRET real y sin role admin (no
bypassa autorización). El caché de authz lo limpia el autouse de
`tests/fastapi/conftest.py`, así que el patch de `has_any_assignment` no se
saltea por un HIT stale de Redis.
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

URL = "/help-desk/"


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


class TestLandingGet:
    def test_sin_asignacion_en_la_app_renderiza_el_403_verde(
        self, app_client, auth_headers
    ):
        # Sin asignación en helpdesk → require_page_app lanza PageForbidden.
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=False,
        ):
            r = app_client.get(URL, headers=auth_headers, follow_redirects=False)

        assert r.status_code == 403, f"esperado 403, fue {r.status_code}"
        assert "text/html" in r.headers["content-type"]
        body = r.text
        # Página de error de Help-Desk (no el landing) con botón al panel core.
        assert "Error 403 - Help-Desk" in body
        assert "Ir al panel principal" in body
        assert "/itcj/dashboard" in body
        # Botón de salida → script que avisa al parent (cierra la ventana).
        assert "CLOSE_APP" in body
        # No es el landing: nada del CTA «Pedir Ayuda» ni redirige.
        assert "Pedir Ayuda" not in body
        assert r.headers.get("location") is None

    def test_con_asignacion_en_la_app_responde_el_landing(
        self, app_client, auth_headers
    ):
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=set(),
        ), patch(
            "itcj2.core.services.authz_service.user_roles_in_app",
            return_value=set(),
        ), patch(
            "itcj2.apps.helpdesk.utils.warehouse_auth.get_warehouse_perms_via_helpdesk",
            return_value=set(),
        ):
            r = app_client.get(URL, headers=auth_headers, follow_redirects=False)

        assert r.status_code == 200, f"esperado 200, fue {r.status_code}"
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "Pedir Ayuda" in body
        assert "Ir al panel principal" not in body
        assert "CLOSE_APP" not in body

    def test_sin_sesion_sigue_redirigiendo_a_login(self, app_client):
        r = app_client.get(URL, follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"


class TestLandingPostSinCambio:
    def test_post_sin_roles_sigue_respondiendo_no_roles_json(
        self, app_client, auth_headers
    ):
        # «Pedir ayuda» no pasa por require_page_app: solo exige sesión y
        # responde JSON 403 `no_roles` cuando el usuario no tiene rol.
        with patch(
            "itcj2.core.services.authz_service.user_roles_in_app",
            return_value=set(),
        ):
            r = app_client.post(URL, headers=auth_headers, follow_redirects=False)

        assert r.status_code == 403
        assert r.json() == {"error": "no_roles"}
