"""F1a (D6): details de users.py y notifications.py humanizados a español."""
from unittest.mock import patch


def test_user_me_not_found_is_human_string(app_client, auth_headers):
    with patch("itcj2.core.api.users._get_user", return_value=None):
        resp = app_client.get("/api/core/v2/user/me", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Usuario no encontrado"


def test_notification_mark_read_not_found_is_human_string(app_client, auth_headers):
    with patch(
        "itcj2.core.services.notification_service.NotificationService.mark_read",
        return_value=False,
    ):
        resp = app_client.patch(
            "/api/core/v2/notifications/999999/read", headers=auth_headers
        )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Notificación no encontrada"
