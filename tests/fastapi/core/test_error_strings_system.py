"""F1a (D6): detail de errores de tasks.py y themes.py = string."""
from unittest.mock import MagicMock, patch

from itcj2.database import get_db


def test_task_run_not_found_error_is_string(app_client, auth_headers):
    mock_db = MagicMock()
    mock_db.get.return_value = None

    def override():
        yield mock_db

    app_client.app.dependency_overrides[get_db] = override
    try:
        resp = app_client.get("/api/core/v2/tasks/runs/999999", headers=auth_headers)
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Ejecución no encontrada"


def test_theme_not_found_error_is_string(app_client, auth_headers):
    with patch("itcj2.core.services.themes_service.get_theme", return_value=None), \
         patch("itcj2.core.services.authz_cache.cached_roles",
               return_value={"admin"}):
        resp = app_client.get("/api/core/v2/themes/999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Temática no encontrada"
