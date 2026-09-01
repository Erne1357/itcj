"""
Tests para /api/core/v2/auth (login, me, logout).
"""
import logging
from unittest.mock import patch

import jwt
import pytest

from tests.conftest import (
    FAKE_STAFF,
    FAKE_STUDENT,
    FakeUser,
    make_jwt,
    make_expired_jwt,
    TEST_SECRET,
)


# ───────────────────────────────────────────────────────────────────
# Health check (sanity)
# ───────────────────────────────────────────────────────────────────
class TestHealthCheck:
    def test_health(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["server"] == "fastapi"


# ───────────────────────────────────────────────────────────────────
# POST /api/core/v2/auth/login
# ───────────────────────────────────────────────────────────────────
class TestLogin:
    @patch("itcj2.core.services.auth_service.authenticate")
    def test_login_student_success(self, mock_auth, app_client):
        """Login exitoso con número de control (8 dígitos)."""
        mock_auth.return_value = FAKE_STUDENT

        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "20210001", "nip": "mypassword"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == 100
        assert data["user"]["role"] == "student"

        # Debe setear la cookie itcj_token
        assert "itcj_token" in resp.cookies

    @patch("itcj2.core.services.auth_service.authenticate")
    def test_login_student_alnum_control_number(self, mock_auth, app_client):
        """Reingreso/posgrado (B*/C*/D*/M*) autentica por control_number, no por username."""
        mock_auth.return_value = FAKE_STUDENT

        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "m23111964", "nip": "mypassword"},
        )

        assert resp.status_code == 200
        # El no. de control se normaliza a mayúsculas antes de buscarlo en BD.
        assert mock_auth.call_args.args[1] == "M23111964"

    @patch("itcj2.core.services.auth_service.authenticate_by_username")
    def test_login_staff_success(self, mock_auth, app_client):
        """Login exitoso con username (staff)."""
        mock_auth.return_value = FAKE_STAFF

        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "mmartinez", "nip": "tecno#2K"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == 200
        assert "itcj_token" in resp.cookies

    @patch("itcj2.core.services.auth_service.authenticate")
    def test_login_invalid_credentials(self, mock_auth, app_client):
        """Login con credenciales incorrectas."""
        mock_auth.return_value = None

        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "20210001", "nip": "wrong"},
        )

        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_credentials"

    def test_login_empty_control_number(self, app_client):
        """Login con control_number vacío."""
        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "", "nip": "test"},
        )

        assert resp.status_code == 400

    def test_login_missing_fields(self, app_client):
        """Login sin body o campos requeridos."""
        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={},
        )

        # Pydantic valida que control_number es requerido
        assert resp.status_code == 422

    @patch("itcj2.core.services.auth_service.authenticate")
    def test_login_mints_sv_zero_when_version_unknown(self, mock_auth, app_client):
        """R5: si `current_version` no puede determinar la versión al loguear
        (Redis inalcanzable), el login debe acuñar sv=0, nunca sv=null.

        Contra el código previo a la Tarea 4, `current_version(...)` se
        pasaba directo al payload del JWT: `"sv": None` en vez de `"sv": 0`,
        así que este test falla contra ese código (`payload["sv"] == 0` con
        `payload["sv"]` en realidad `None`).
        """
        mock_auth.return_value = FAKE_STUDENT

        with patch(
            "itcj2.core.services.session_service.current_version",
            return_value=None,
        ):
            resp = app_client.post(
                "/api/core/v2/auth/login",
                json={"control_number": "20210001", "nip": "mypassword"},
            )

        assert resp.status_code == 200
        assert "itcj_token" in resp.cookies
        payload = jwt.decode(
            resp.cookies["itcj_token"],
            TEST_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        assert "sv" in payload
        assert payload["sv"] == 0


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/auth/me
# ───────────────────────────────────────────────────────────────────
class TestMe:
    def test_me_authenticated(self, app_client):
        """GET /me con JWT válido (CON claim `sv`) retorna datos del usuario.

        El token se acuña con `make_jwt(sv=...)` a propósito. Sin el claim, el
        middleware se salta ENTERA la comparación de revocación (rama de
        compatibilidad con tokens anteriores a que existiera `sv`), así que el
        grueso de la suite —que usa `auth_headers`, sin `sv`— recorre un camino
        que producción nunca toma: el login siempre acuña el claim
        (`itcj2/core/api/auth.py`). Con `sv` presente, el middleware llama a
        `current_version` y compara, que es la rama real.

        `current_version` va parcheada porque el usuario 200 de este harness es
        un mock sin fila en `core_users`: sin parche el veredicto dependería del
        `session_epoch` que hubiera en la BD compartida de dev y el test sería
        no-determinista.
        """
        token = make_jwt(user_id=200, role="admin", name="MARTINEZ PEREZ MARIA", sv=4)

        with patch(
            "itcj2.core.services.session_service.current_version", return_value=4
        ):
            resp = app_client.get(
                "/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={token}"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == 200
        assert data["user"]["full_name"] == "MARTINEZ PEREZ MARIA"

    def test_me_revoked_by_session_epoch(self, app_client):
        """La contrapartida que le da sentido al `sv` del test anterior.

        Mismo token, misma ruta; lo único que cambia es que la época vigente
        avanzó (logout, desactivación, cambio de rol). Si el middleware ignorara
        el claim —la rama de compatibilidad—, esto devolvería 200 y una sesión ya
        revocada seguiría dentro.
        """
        token = make_jwt(user_id=200, role="admin", name="MARTINEZ PEREZ MARIA", sv=4)

        with patch(
            "itcj2.core.services.session_service.current_version", return_value=5
        ):
            resp = app_client.get(
                "/api/core/v2/auth/me", headers={"Cookie": f"itcj_token={token}"}
            )

        assert resp.status_code == 401

    def test_me_student(self, app_client, student_headers):
        """GET /me con JWT de estudiante retorna control_number."""
        resp = app_client.get("/api/core/v2/auth/me", headers=student_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == 100
        assert data["user"]["control_number"] == "20210001"

    def test_me_unauthenticated(self, app_client):
        """GET /me sin JWT retorna 401."""
        resp = app_client.get("/api/core/v2/auth/me")

        assert resp.status_code == 401

    def test_me_expired_token(self, app_client):
        """GET /me con JWT expirado retorna 401."""
        token = make_expired_jwt()
        resp = app_client.get(
            "/api/core/v2/auth/me",
            headers={"Cookie": f"itcj_token={token}"},
        )

        assert resp.status_code == 401

    def test_me_invalid_token(self, app_client):
        """GET /me con JWT inválido retorna 401."""
        resp = app_client.get(
            "/api/core/v2/auth/me",
            headers={"Cookie": "itcj_token=notavalidjwt"},
        )

        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# POST /api/core/v2/auth/logout
# ───────────────────────────────────────────────────────────────────
class TestLogout:
    def test_logout_success(self, app_client, auth_headers):
        """Logout exitoso limpia la cookie."""
        resp = app_client.post("/api/core/v2/auth/logout", headers=auth_headers)

        assert resp.status_code == 204

        # La cookie debe limpiarse (max-age=0 o valor vacío)
        cookie = resp.headers.get("set-cookie", "")
        assert "itcj_token" in cookie

    def test_logout_unauthenticated(self, app_client):
        """Logout sin sesión retorna 401."""
        resp = app_client.post("/api/core/v2/auth/logout")

        assert resp.status_code == 401

    def test_logout_logs_when_revocation_fails(self, app_client, auth_headers, caplog):
        """Un logout que no pudo revocar no puede quedarse MUDO.

        Logout es el único sitio de revocación que sigue adelante cuando el bump
        falla, y con razón: devolver 500 a quien pidió salir es peor UX que
        dejarlo salir. Pero el token sigue VIVO hasta que expire (12h), así que
        el fallo tiene que quedar en los logs — antes era `except: pass` con el
        retorno sin mirar y no dejaba rastro de ningún tipo.

        El endurecimiento equivalente de los otros dos sitios sí aborta:
        `toggle_user_status` lanza 500 y el batch de agendatec omite al alumno.
        """
        with patch(
            "itcj2.core.services.session_service.bump_version", return_value=None
        ), caplog.at_level(logging.ERROR, logger="itcj2.core.api.auth"):
            resp = app_client.post("/api/core/v2/auth/logout", headers=auth_headers)

        assert resp.status_code == 204
        assert any(
            "no se pudo revocar" in rec.getMessage().lower() for rec in caplog.records
        ), caplog.text

    def test_logout_logs_when_revocation_raises(self, app_client, auth_headers, caplog):
        """Igual que el anterior, pero con `bump_version` lanzando."""
        with patch(
            "itcj2.core.services.session_service.bump_version",
            side_effect=RuntimeError("bd caida"),
        ), caplog.at_level(logging.ERROR, logger="itcj2.core.api.auth"):
            resp = app_client.post("/api/core/v2/auth/logout", headers=auth_headers)

        assert resp.status_code == 204
        assert any(
            "bump_version lanzo" in rec.getMessage().lower() for rec in caplog.records
        ), caplog.text
