"""
Tests para /api/core/v2/auth (login, me, logout).
"""
from unittest.mock import patch

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
    @patch("itcj.core.services.auth_service.authenticate")
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

    @patch("itcj.core.services.auth_service.authenticate_by_username")
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

    @patch("itcj.core.services.auth_service.authenticate")
    def test_login_invalid_credentials(self, mock_auth, app_client):
        """Login con credenciales incorrectas."""
        mock_auth.return_value = None

        resp = app_client.post(
            "/api/core/v2/auth/login",
            json={"control_number": "20210001", "nip": "wrong"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid_credentials"

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


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/auth/me
# ───────────────────────────────────────────────────────────────────
class TestMe:
    def test_me_authenticated(self, app_client, auth_headers):
        """GET /me con JWT válido retorna datos del usuario."""
        resp = app_client.get("/api/core/v2/auth/me", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == 200
        assert data["user"]["full_name"] == "MARTINEZ PEREZ MARIA"

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
