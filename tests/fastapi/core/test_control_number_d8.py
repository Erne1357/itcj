"""D8/C7: numero de control = ^[A-Za-z]?\\d{8}$ en create y update (revisado 2026-09-17).

Acepta: 12345678 (formato normal), B21221523 (traslado, letra + 8 digitos).
Rechaza: 123456789 (9 digitos puros), 1234567 (7 digitos), M2111118 (letra +
7 digitos, formato viejo de posgrado), M211111822 (letra + 9 digitos, formato
viejo de posgrado, retirado), MM111182 (dos letras), vacio.

La letra se normaliza a MAYUSCULA (y se recorta el espacio) antes de validar
y de guardar: los lookups son `filter_by(control_number=...)` exactos, y una
'b' minuscula duplicaria cuentas frente a una 'B' ya existente.
"""
from unittest.mock import MagicMock, patch

import pytest

from itcj2.database import get_db

VALID = ["12345678", "B21221523"]
INVALID = ["123456789", "1234567", "M2111118", "M211111822", "MM111182", ""]


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

    def test_lowercase_letter_is_normalized_to_uppercase(self, app_client, auth_headers):
        """`b21221523` se guarda como `B21221523`: el lookup exacto de
        `filter_by(control_number=...)` no perdona el case, y una letra en
        minuscula duplicaria la cuenta frente a una ya existente en mayuscula."""
        def override():
            yield _db_for_create()

        app_client.app.dependency_overrides[get_db] = override
        try:
            resp = _post_create(app_client, auth_headers, "b21221523")
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["control_number"] == "B21221523"


class TestUpdateControlNumber:
    def _db_for_update(self):
        u = MagicMock()
        u.control_number = "12345678"  # es estudiante → aplica la rama de update
        u.to_dict.return_value = {"id": 1}
        db = MagicMock()
        # db.get(User, id), no el db.query(User).get(id) legacy: con MagicMock
        # mockear el metodo viejo devuelve un Mock en vez de `u`, y el test pasa
        # sin ejercitar de verdad la rama de estudiante.
        db.get.return_value = u
        db.query.return_value.filter.return_value.first.return_value = None
        return db

    def _patch(self, db, app_client, auth_headers, ctrl):
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
        resp = self._patch(self._db_for_update(), app_client, auth_headers, ctrl)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("ctrl", ["123456789", "MM111182", "M2111118", "M211111822"])
    def test_rejects_invalid(self, app_client, auth_headers, ctrl):
        resp = self._patch(self._db_for_update(), app_client, auth_headers, ctrl)
        assert resp.status_code == 400

    def test_lowercase_letter_is_normalized_to_uppercase(self, app_client, auth_headers):
        """Misma normalizacion que create: `b21221523` -> `B21221523` antes de
        buscar duplicados y de guardar."""
        db = self._db_for_update()
        resp = self._patch(db, app_client, auth_headers, "b21221523")
        assert resp.status_code == 200, resp.text
        assert db.get.return_value.control_number == "B21221523"
