"""F1a (D6): detail de errores de departments.py y positions.py = string."""
from unittest.mock import patch


def test_create_department_validation_error_is_string(app_client, auth_headers):
    resp = app_client.post(
        "/api/core/v2/departments",
        json={"code": "  ", "name": "  "},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "El código y el nombre son requeridos"


def test_create_position_validation_error_is_string(app_client, auth_headers):
    resp = app_client.post(
        "/api/core/v2/positions",
        json={"code": "  ", "title": "  "},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "El código y el título son requeridos"


def test_position_not_found_error_is_string(app_client, auth_headers):
    with patch("itcj2.core.services.positions_service.get_position_by_id",
               return_value=None):
        resp = app_client.get("/api/core/v2/positions/999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Puesto no encontrado"
