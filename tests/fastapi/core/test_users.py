"""
Tests para /api/core/v2/user (perfil, contraseña, actividad, notificaciones).
"""
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import FakeUser, TEST_SECRET


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/user/password-state
# ───────────────────────────────────────────────────────────────────
class TestPasswordState:
    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"admin"})
    @patch("itcj.core.utils.security.verify_nip", return_value=True)
    def test_must_change_default_password(self, mock_verify, mock_roles, app_client, auth_headers):
        """Staff con contraseña por defecto → must_change=True."""
        fake_user = FakeUser(id=200, username="mmartinez", role_name="admin")

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            resp = app_client.get(
                "/api/core/v2/user/password-state", headers=auth_headers
            )

        assert resp.status_code == 200
        assert resp.json()["must_change"] is True

    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"admin"})
    @patch("itcj.core.utils.security.verify_nip", return_value=False)
    def test_password_already_changed(self, mock_verify, mock_roles, app_client, auth_headers):
        """Staff con contraseña ya cambiada → must_change=False."""
        fake_user = FakeUser(id=200, username="mmartinez")

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            resp = app_client.get(
                "/api/core/v2/user/password-state", headers=auth_headers
            )

        assert resp.status_code == 200
        assert resp.json()["must_change"] is False

    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"student"})
    def test_student_never_must_change(self, mock_roles, app_client, student_headers):
        """Estudiantes nunca deben cambiar contraseña."""
        fake_user = FakeUser(id=100, control_number="20210001", role_name="student")

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            resp = app_client.get(
                "/api/core/v2/user/password-state", headers=student_headers
            )

        assert resp.status_code == 200
        assert resp.json()["must_change"] is False

    def test_unauthenticated(self, app_client):
        resp = app_client.get("/api/core/v2/user/password-state")
        assert resp.status_code == 401

    def test_user_not_found(self, app_client, auth_headers):
        with patch("itcj2.core.api.users._get_user", return_value=None):
            resp = app_client.get(
                "/api/core/v2/user/password-state", headers=auth_headers
            )
        assert resp.status_code == 404


# ───────────────────────────────────────────────────────────────────
# POST /api/core/v2/user/change-password
# ───────────────────────────────────────────────────────────────────
class TestChangePassword:
    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"admin"})
    @patch("itcj.core.utils.security.hash_nip", return_value="new_hash")
    def test_change_password_success(self, mock_hash, mock_roles, app_client, auth_headers):
        """Cambio de contraseña exitoso."""
        fake_user = FakeUser(id=200, username="mmartinez")
        mock_db = MagicMock()

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            with patch("itcj2.database.SessionLocal", return_value=mock_db):
                resp = app_client.post(
                    "/api/core/v2/user/change-password",
                    json={"new_password": "newSecurePass123"},
                    headers=auth_headers,
                )

        assert resp.status_code == 200
        assert resp.json()["message"] == "password_updated"
        assert fake_user.password_hash == "new_hash"

    def test_change_password_too_short(self, app_client, auth_headers):
        """Contraseña muy corta (< 8 chars) → 422."""
        resp = app_client.post(
            "/api/core/v2/user/change-password",
            json={"new_password": "short"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"admin"})
    def test_change_password_default_rejected(self, mock_roles, app_client, auth_headers):
        """No se puede usar la contraseña por defecto."""
        fake_user = FakeUser(id=200, username="mmartinez")

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            resp = app_client.post(
                "/api/core/v2/user/change-password",
                json={"new_password": "tecno#2K"},
                headers=auth_headers,
            )

        assert resp.status_code == 400

    @patch("itcj.core.services.authz_service.user_roles_in_app", return_value={"student"})
    def test_student_cannot_change_password(self, mock_roles, app_client, student_headers):
        """Estudiantes no pueden cambiar contraseña."""
        fake_user = FakeUser(id=100, control_number="20210001", role_name="student")

        with patch("itcj2.core.api.users._get_user", return_value=fake_user):
            resp = app_client.post(
                "/api/core/v2/user/change-password",
                json={"new_password": "newSecurePass123"},
                headers=student_headers,
            )

        assert resp.status_code == 403

    def test_unauthenticated(self, app_client):
        resp = app_client.post(
            "/api/core/v2/user/change-password",
            json={"new_password": "something"},
        )
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/user/me
# ───────────────────────────────────────────────────────────────────
class TestGetCurrentUser:
    @patch("itcj.core.services.authz_service.user_roles_in_app")
    def test_get_user_info(self, mock_roles, app_client, auth_headers):
        """Obtener información del usuario actual."""
        mock_roles.return_value = {"admin"}

        fake_user = FakeUser(
            id=200,
            username="mmartinez",
            first_name="MARIA",
            last_name="MARTINEZ",
            middle_name="PEREZ",
            email="mmartinez@cdjuarez.tecnm.mx",
        )

        # Mock App query
        mock_app = MagicMock()
        mock_app.key = "itcj"

        # Mock db session inyectada por FastAPI
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_app]
        mock_db.query.return_value.filter_by.return_value.all.return_value = []
        mock_db.query.return_value.get.return_value = fake_user

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        # Override the FastAPI dependency
        from itcj2.main import create_app
        app_client.app.dependency_overrides[get_db] = override_get_db

        try:
            with patch("itcj2.core.api.users._get_user", return_value=fake_user):
                resp = app_client.get(
                    "/api/core/v2/user/me", headers=auth_headers
                )

            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["id"] == 200
            assert data["username"] == "mmartinez"
            assert "MARTINEZ" in data["full_name"]
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

    def test_get_user_not_found(self, app_client, auth_headers):
        with patch("itcj2.core.api.users._get_user", return_value=None):
            resp = app_client.get(
                "/api/core/v2/user/me", headers=auth_headers
            )
        assert resp.status_code == 404

    def test_unauthenticated(self, app_client):
        resp = app_client.get("/api/core/v2/user/me")
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/user/me/profile
# ───────────────────────────────────────────────────────────────────
class TestGetFullProfile:
    @patch("itcj.core.services.profile_service.get_user_profile_data")
    def test_full_profile(self, mock_profile, app_client, auth_headers):
        """Perfil completo retorna datos del servicio."""
        mock_profile.return_value = {
            "id": 200,
            "full_name": "MARTINEZ PEREZ MARIA",
            "positions": [],
            "apps": {},
        }

        resp = app_client.get("/api/core/v2/user/me/profile", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 200
        mock_profile.assert_called_once_with(200)

    @patch("itcj.core.services.profile_service.get_user_profile_data", return_value=None)
    def test_profile_not_found(self, mock_profile, app_client, auth_headers):
        resp = app_client.get("/api/core/v2/user/me/profile", headers=auth_headers)
        assert resp.status_code == 404


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/user/me/activity
# ───────────────────────────────────────────────────────────────────
class TestGetActivity:
    @patch("itcj.core.services.profile_service.get_user_activity")
    def test_activity(self, mock_activity, app_client, auth_headers):
        mock_activity.return_value = [{"action": "login", "ts": "2026-02-24"}]

        resp = app_client.get("/api/core/v2/user/me/activity", headers=auth_headers)

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1
        mock_activity.assert_called_once_with(200, limit=10)

    @patch("itcj.core.services.profile_service.get_user_activity")
    def test_activity_with_limit(self, mock_activity, app_client, auth_headers):
        mock_activity.return_value = []

        resp = app_client.get(
            "/api/core/v2/user/me/activity?limit=5", headers=auth_headers
        )

        assert resp.status_code == 200
        mock_activity.assert_called_once_with(200, limit=5)

    def test_activity_limit_too_high(self, app_client, auth_headers):
        """Limit > 50 debe ser rechazado por Pydantic."""
        resp = app_client.get(
            "/api/core/v2/user/me/activity?limit=999", headers=auth_headers
        )
        assert resp.status_code == 422


# ───────────────────────────────────────────────────────────────────
# PATCH /api/core/v2/user/me/profile
# ───────────────────────────────────────────────────────────────────
class TestUpdateProfile:
    def test_update_email(self, app_client, auth_headers):
        """Actualizar email."""
        fake_user = FakeUser(id=200, email="old@test.com")
        mock_db = MagicMock()
        mock_db.query.return_value.get.return_value = fake_user

        with patch("itcj2.database.SessionLocal", return_value=mock_db):
            resp = app_client.patch(
                "/api/core/v2/user/me/profile",
                json={"email": "new@test.com"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unauthenticated(self, app_client):
        resp = app_client.patch(
            "/api/core/v2/user/me/profile",
            json={"email": "new@test.com"},
        )
        assert resp.status_code == 401
