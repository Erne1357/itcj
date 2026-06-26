"""
Tests para los endpoints de gestión de secretarias del jefe de departamento.

Rutas cubiertas:
  GET  /api/help-desk/v2/department-head/secretaries
  POST /api/help-desk/v2/department-head/secretaries/{id}/reset-password
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FakeUser

BASE = "/api/help-desk/v2/department-head"


# ---------------------------------------------------------------------------
# Helpers de factory
# ---------------------------------------------------------------------------

def _make_secretary(**kwargs):
    """Devuelve un FakeUser con atributos de secretaria."""
    defaults = dict(
        id=42,
        username="lmartinez",
        first_name="LUCIA",
        last_name="MARTINEZ",
        email="lmartinez@cdjuarez.tecnm.mx",
        must_change_password=False,
        is_active=True,
    )
    defaults.update(kwargs)
    return FakeUser(**defaults)


# ---------------------------------------------------------------------------
# GET /secretaries
# ---------------------------------------------------------------------------

class TestListSecretaries:
    """GET /api/help-desk/v2/department-head/secretaries"""

    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(10, "dev"),
    )
    def test_ok(self, mock_dept_code, app_client, auth_headers):
        """Caller con dept_code='dev', secretaria encontrada → 200 con 1 item."""
        secretary = _make_secretary()

        mock_db = MagicMock()
        # Simular query encadenada que retorna la lista de secretarias
        mock_db.query.return_value.join.return_value.join.return_value.filter.return_value.all.return_value = [
            secretary
        ]

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.get(f"{BASE}/secretaries", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["total"] == 1
        assert body["data"][0]["id"] == 42
        assert body["data"][0]["username"] == "lmartinez"
        assert "must_change_password" in body["data"][0]

    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(None, None),
    )
    def test_no_department(self, mock_dept_code, app_client, auth_headers):
        """Caller sin puesto activo → 403."""
        mock_db = MagicMock()

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.get(f"{BASE}/secretaries", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 403
        # La app usa un exception handler custom: {"error": ..., "status": ...}
        assert "departamento" in resp.json()["error"].lower()

    def test_unauthenticated(self, app_client):
        """Sin cookie de autenticación → 401."""
        resp = app_client.get(f"{BASE}/secretaries")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /secretaries/{id}/reset-password
# ---------------------------------------------------------------------------

class TestResetSecretaryPassword:
    """POST /api/help-desk/v2/department-head/secretaries/{id}/reset-password"""

    @patch("itcj2.core.utils.security.hash_nip", return_value="hashed_tecno_2K")
    @patch(
        "itcj2.apps.helpdesk.api.department_head._is_head_of_dept",
        return_value=True,
    )
    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(10, "dev"),
    )
    def test_ok(self, mock_dept_code, mock_is_head, mock_hash, app_client, auth_headers):
        """Caller es jefe, target es secretaria del mismo depto → 200."""
        secretary = _make_secretary(id=42)

        mock_db = MagicMock()
        mock_db.get.return_value = secretary
        # Simular que la verificación de secretaria encuentra el puesto
        mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = MagicMock()

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/secretaries/42/reset-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["user_id"] == 42
        assert body["data"]["must_change_password"] is True
        assert secretary.must_change_password is True
        assert secretary.password_hash == "hashed_tecno_2K"
        mock_db.commit.assert_called_once()

    @patch(
        "itcj2.apps.helpdesk.api.department_head._is_head_of_dept",
        return_value=True,
    )
    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(10, "dev"),
    )
    def test_target_not_found(self, mock_dept_code, mock_is_head, app_client, auth_headers):
        """Target no existe en BD → 404."""
        mock_db = MagicMock()
        mock_db.get.return_value = None  # Usuario no encontrado

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/secretaries/9999/reset-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 404

    @patch(
        "itcj2.apps.helpdesk.api.department_head._is_head_of_dept",
        return_value=False,
    )
    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(10, "dev"),
    )
    def test_not_head(self, mock_dept_code, mock_is_head, app_client, auth_headers):
        """Caller no tiene puesto head_dev → 403."""
        mock_db = MagicMock()

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/secretaries/42/reset-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 403
        # La app usa un exception handler custom: {"error": ..., "status": ...}
        assert "jefe" in resp.json()["error"].lower()

    @patch(
        "itcj2.apps.helpdesk.api.department_head._is_head_of_dept",
        return_value=True,
    )
    @patch(
        "itcj2.apps.helpdesk.api.department_head._get_department_code",
        return_value=(10, "dev"),
    )
    def test_cross_dept(self, mock_dept_code, mock_is_head, app_client, auth_headers):
        """Target es secretaria pero de otro depto → 403."""
        secretary = _make_secretary(id=77)

        mock_db = MagicMock()
        mock_db.get.return_value = secretary
        # La verificación de secretaria NO encuentra el puesto (None → cross-dept)
        mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = None

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/secretaries/77/reset-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 403
        # La app usa un exception handler custom: {"error": ..., "status": ...}
        assert "secretaria" in resp.json()["error"].lower()

    def test_unauthenticated(self, app_client):
        """Sin cookie de autenticación → 401."""
        resp = app_client.post(f"{BASE}/secretaries/42/reset-password")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /reset-my-password
# ---------------------------------------------------------------------------

class TestResetMyPassword:
    """POST /api/help-desk/v2/department-head/reset-my-password"""

    @patch("itcj2.core.utils.security.hash_nip", return_value="hashed_tecno_2K")
    def test_ok(self, mock_hash, app_client, auth_headers):
        """El jefe restablece su propia contraseña → 200, queda en tecno#2K + must_change."""
        me = FakeUser(id=200, username="jefe")

        mock_db = MagicMock()
        mock_db.get.return_value = me

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/reset-my-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["user_id"] == 200
        assert body["data"]["must_change_password"] is True
        assert me.must_change_password is True
        assert me.password_hash == "hashed_tecno_2K"
        mock_db.commit.assert_called_once()

    @patch("itcj2.core.utils.security.hash_nip", return_value="hashed_tecno_2K")
    def test_user_not_found(self, mock_hash, app_client, auth_headers):
        """El usuario del token no existe en BD → 404."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        from itcj2.database import get_db

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            resp = app_client.post(f"{BASE}/reset-my-password", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 404

    def test_unauthenticated(self, app_client):
        """Sin cookie de autenticación → 401."""
        resp = app_client.post(f"{BASE}/reset-my-password")
        assert resp.status_code == 401
