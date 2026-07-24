"""F1a (D6): detail de errores de users_admin.py = string humano, no dict."""
from unittest.mock import MagicMock, patch

from itcj2.database import get_db


def test_create_user_invalid_type_error_is_string(app_client, auth_headers):
    resp = app_client.post(
        "/api/core/v2/users",
        json={"full_name": "Juan Perez", "user_type": "alien", "password": "x12345678"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert isinstance(body["error"], str)
    assert body["error"] == "Tipo de usuario inválido"


def test_toggle_missing_user_error_is_string(app_client, auth_headers):
    mock_db = MagicMock()
    mock_db.query.return_value.get.return_value = None

    def override():
        yield mock_db

    app_client.app.dependency_overrides[get_db] = override
    try:
        with patch("itcj2.core.services.authz_cache.cached_roles",
                   return_value={"admin"}):
            resp = app_client.post(
                "/api/core/v2/users/999999/toggle-status", headers=auth_headers
            )
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Usuario no encontrado"
