"""
Tests para /api/core/v2/notifications (listado, marcar leídas, eliminar).
"""
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest


# ───────────────────────────────────────────────────────────────────
# Fake notification data
# ───────────────────────────────────────────────────────────────────
FAKE_NOTIFICATION = {
    "id": 1,
    "app_name": "helpdesk",
    "type": "TICKET_ASSIGNED",
    "title": "Ticket asignado",
    "body": "Se te ha asignado el ticket #1234",
    "is_read": False,
    "created_at": "2026-02-24T10:00:00",
}

FAKE_NOTIFICATIONS_RESPONSE = {
    "items": [FAKE_NOTIFICATION],
    "total": 1,
    "unread": 1,
    "has_more": False,
}


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/notifications
# ───────────────────────────────────────────────────────────────────
class TestListNotifications:
    @patch("itcj.core.services.notification_service.NotificationService")
    def test_list_all(self, mock_svc, app_client, auth_headers):
        """Listar todas las notificaciones del usuario."""
        mock_svc.get_notifications.return_value = FAKE_NOTIFICATIONS_RESPONSE

        resp = app_client.get("/api/core/v2/notifications", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["type"] == "TICKET_ASSIGNED"

        mock_svc.get_notifications.assert_called_once_with(
            user_id=200,
            app_name=None,
            unread_only=False,
            limit=20,
            offset=0,
            before_id=None,
        )

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_list_filtered_by_app(self, mock_svc, app_client, auth_headers):
        """Filtrar notificaciones por app."""
        mock_svc.get_notifications.return_value = FAKE_NOTIFICATIONS_RESPONSE

        resp = app_client.get(
            "/api/core/v2/notifications?app=helpdesk", headers=auth_headers
        )

        assert resp.status_code == 200
        mock_svc.get_notifications.assert_called_once_with(
            user_id=200,
            app_name="helpdesk",
            unread_only=False,
            limit=20,
            offset=0,
            before_id=None,
        )

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_list_unread_only(self, mock_svc, app_client, auth_headers):
        """Filtrar solo no leídas."""
        mock_svc.get_notifications.return_value = FAKE_NOTIFICATIONS_RESPONSE

        resp = app_client.get(
            "/api/core/v2/notifications?unread=true", headers=auth_headers
        )

        assert resp.status_code == 200
        mock_svc.get_notifications.assert_called_once_with(
            user_id=200,
            app_name=None,
            unread_only=True,
            limit=20,
            offset=0,
            before_id=None,
        )

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_list_with_pagination(self, mock_svc, app_client, auth_headers):
        """Paginación con limit y offset."""
        mock_svc.get_notifications.return_value = {
            "items": [],
            "total": 50,
            "unread": 10,
            "has_more": True,
        }

        resp = app_client.get(
            "/api/core/v2/notifications?limit=5&offset=10", headers=auth_headers
        )

        assert resp.status_code == 200
        mock_svc.get_notifications.assert_called_once_with(
            user_id=200,
            app_name=None,
            unread_only=False,
            limit=5,
            offset=10,
            before_id=None,
        )

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_list_with_cursor(self, mock_svc, app_client, auth_headers):
        """Paginación basada en cursor (before_id)."""
        mock_svc.get_notifications.return_value = FAKE_NOTIFICATIONS_RESPONSE

        resp = app_client.get(
            "/api/core/v2/notifications?before_id=50", headers=auth_headers
        )

        assert resp.status_code == 200
        mock_svc.get_notifications.assert_called_once_with(
            user_id=200,
            app_name=None,
            unread_only=False,
            limit=20,
            offset=0,
            before_id=50,
        )

    def test_list_unauthenticated(self, app_client):
        resp = app_client.get("/api/core/v2/notifications")
        assert resp.status_code == 401

    def test_list_limit_too_high(self, app_client, auth_headers):
        """Limit > 100 debe ser rechazado."""
        resp = app_client.get(
            "/api/core/v2/notifications?limit=200", headers=auth_headers
        )
        assert resp.status_code == 422


# ───────────────────────────────────────────────────────────────────
# GET /api/core/v2/notifications/unread-counts
# ───────────────────────────────────────────────────────────────────
class TestUnreadCounts:
    @patch("itcj.core.services.notification_service.NotificationService")
    def test_unread_counts(self, mock_svc, app_client, auth_headers):
        """Obtener conteos de no leídas por app."""
        mock_svc.get_unread_counts_by_app.return_value = {
            "helpdesk": 3,
            "agendatec": 1,
        }

        resp = app_client.get(
            "/api/core/v2/notifications/unread-counts", headers=auth_headers
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["counts"]["helpdesk"] == 3
        assert data["total"] == 4

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_unread_counts_empty(self, mock_svc, app_client, auth_headers):
        """Sin notificaciones no leídas."""
        mock_svc.get_unread_counts_by_app.return_value = {}

        resp = app_client.get(
            "/api/core/v2/notifications/unread-counts", headers=auth_headers
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    def test_unauthenticated(self, app_client):
        resp = app_client.get("/api/core/v2/notifications/unread-counts")
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# PATCH /api/core/v2/notifications/{id}/read
# ───────────────────────────────────────────────────────────────────
class TestMarkRead:
    @patch("itcj.core.services.notification_service.NotificationService")
    def test_mark_read_success(self, mock_svc, app_client, auth_headers):
        """Marcar notificación como leída."""
        mock_svc.mark_read.return_value = True

        resp = app_client.patch(
            "/api/core/v2/notifications/1/read", headers=auth_headers
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_svc.mark_read.assert_called_once_with(1, 200)

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_mark_read_not_found(self, mock_svc, app_client, auth_headers):
        """Notificación no existe o no pertenece al usuario."""
        mock_svc.mark_read.return_value = False

        resp = app_client.patch(
            "/api/core/v2/notifications/999/read", headers=auth_headers
        )

        assert resp.status_code == 404

    def test_unauthenticated(self, app_client):
        resp = app_client.patch("/api/core/v2/notifications/1/read")
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# PATCH /api/core/v2/notifications/mark-all-read
# ───────────────────────────────────────────────────────────────────
class TestMarkAllRead:
    @patch("itcj.core.services.notification_service.NotificationService")
    def test_mark_all_read(self, mock_svc, app_client, auth_headers):
        """Marcar todas como leídas."""
        mock_svc.mark_all_read.return_value = 5

        resp = app_client.patch(
            "/api/core/v2/notifications/mark-all-read", headers=auth_headers
        )

        assert resp.status_code == 200
        assert resp.json()["count"] == 5
        mock_svc.mark_all_read.assert_called_once_with(200, None)

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_mark_all_read_filtered(self, mock_svc, app_client, auth_headers):
        """Marcar todas como leídas filtradas por app."""
        mock_svc.mark_all_read.return_value = 2

        resp = app_client.patch(
            "/api/core/v2/notifications/mark-all-read?app=helpdesk",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        mock_svc.mark_all_read.assert_called_once_with(200, "helpdesk")

    def test_unauthenticated(self, app_client):
        resp = app_client.patch("/api/core/v2/notifications/mark-all-read")
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────
# DELETE /api/core/v2/notifications/{id}
# ───────────────────────────────────────────────────────────────────
class TestDeleteNotification:
    @patch("itcj.core.services.notification_service.NotificationService")
    def test_delete_success(self, mock_svc, app_client, auth_headers):
        """Eliminar notificación."""
        mock_svc.delete_notification.return_value = True

        resp = app_client.delete(
            "/api/core/v2/notifications/1", headers=auth_headers
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_svc.delete_notification.assert_called_once_with(1, 200)

    @patch("itcj.core.services.notification_service.NotificationService")
    def test_delete_not_found(self, mock_svc, app_client, auth_headers):
        """Eliminar notificación que no existe."""
        mock_svc.delete_notification.return_value = False

        resp = app_client.delete(
            "/api/core/v2/notifications/999", headers=auth_headers
        )

        assert resp.status_code == 404

    def test_unauthenticated(self, app_client):
        resp = app_client.delete("/api/core/v2/notifications/1")
        assert resp.status_code == 401
