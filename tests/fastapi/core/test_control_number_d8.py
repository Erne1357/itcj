"""D8/C7: numero de control = ^(\\d{8}|[A-Za-z]\\d{7,9})$ en create y update.

Acepta: 12345678 (licenciatura), M2111118 (letra+7), M211111822 (letra+9).
Rechaza: 123456789 (9 digitos numericos), 1234567, MM111182, vacio.
"""
from unittest.mock import MagicMock, patch

import pytest

from itcj2.database import get_db

VALID = ["12345678", "M2111118", "M211111822"]
INVALID = ["123456789", "1234567", "MM111182", ""]


def _db_for_create():
    from itcj2.core.models.user import User

    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is User:
            q.filter_by.return_value.first.return_value = None  # sin duplicados
        else:  # Role
            role = MagicMock()
            role.id = 7
            q.filter_by.return_value.first.return_value = role
        return q

    db.query.side_effect = query_side_effect
    return db


def _post_create(app_client, auth_headers, ctrl):
    return app_client.post(
        "/api/core/v2/users",
        json={
            "full_name": "Prueba Alumno",
            "user_type": "student",
            "control_number": ctrl,
            "password": "x12345678",
        },
        headers=auth_headers,
    )


class TestCreateControlNumber:
    @pytest.mark.parametrize("ctrl", VALID)
    def test_accepts_valid(self, app_client, auth_headers, ctrl):
        def override():
            yield _db_for_create()

        app_client.app.dependency_overrides[get_db] = override
        try:
            resp = _post_create(app_client, auth_headers, ctrl)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)
        assert resp.status_code == 201, resp.text

    @pytest.mark.parametrize("ctrl", INVALID)
    def test_rejects_invalid(self, app_client, auth_headers, ctrl):
        resp = _post_create(app_client, auth_headers, ctrl)
        assert resp.status_code == 400
        assert isinstance(resp.json()["error"], str)


class TestUpdateControlNumber:
    def _db_for_update(self):
        u = MagicMock()
        u.control_number = "12345678"  # es estudiante → aplica la rama de update
        u.to_dict.return_value = {"id": 1}
        db = MagicMock()
        db.query.return_value.get.return_value = u
        db.query.return_value.filter.return_value.first.return_value = None
        return db

    def _patch(self, app_client, auth_headers, ctrl):
        db = self._db_for_update()

        def override():
            yield db

        app_client.app.dependency_overrides[get_db] = override
        try:
            with patch("itcj2.core.services.authz_cache.cached_roles",
                       return_value={"admin"}):
                return app_client.patch(
                    "/api/core/v2/users/1",
                    json={"control_number": ctrl},
                    headers=auth_headers,
                )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

    @pytest.mark.parametrize("ctrl", VALID)
    def test_accepts_valid(self, app_client, auth_headers, ctrl):
        resp = self._patch(app_client, auth_headers, ctrl)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("ctrl", ["123456789", "MM111182"])
    def test_rejects_invalid(self, app_client, auth_headers, ctrl):
        resp = self._patch(app_client, auth_headers, ctrl)
        assert resp.status_code == 400
