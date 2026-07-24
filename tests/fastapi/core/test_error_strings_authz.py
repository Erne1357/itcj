"""F1a (D6): detail de errores de authz.py = string humano, no dict."""
from unittest.mock import MagicMock

from itcj2.database import get_db


def test_create_app_validation_error_is_string(app_client, auth_headers):
    resp = app_client.post(
        "/api/core/v2/authz/apps",
        json={"key": "  ", "name": "  "},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert isinstance(body["error"], str)
    assert body["error"] == "La clave y el nombre son requeridos"


def test_update_missing_app_error_is_string(app_client, auth_headers):
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = None

    def override():
        yield mock_db

    app_client.app.dependency_overrides[get_db] = override
    try:
        resp = app_client.patch(
            "/api/core/v2/authz/apps/no-existe",
            json={"name": "X"},
            headers=auth_headers,
        )
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Aplicación no encontrada"
