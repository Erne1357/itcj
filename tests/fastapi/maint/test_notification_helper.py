"""Tests para itcj2.apps.maint.services.notification_helper.

Verifica anchors en data.url y dedup de recipientes.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper


def _fake_ticket(**kw):
    t = MagicMock()
    t.id = kw.get("id", 7)
    t.ticket_number = kw.get("ticket_number", "MANT-2026-000007")
    t.title = kw.get("title", "Reparar lámpara")
    t.priority = kw.get("priority", "MEDIA")
    t.status = kw.get("status", "RESOLVED_SUCCESS")
    t.requester_id = kw.get("requester_id", 100)
    t.requester_department_id = kw.get("requester_department_id", 5)
    t.cancel_reason = kw.get("cancel_reason", None)
    t.resolved_by_id = kw.get("resolved_by_id", None)
    t.rating_attention = kw.get("rating_attention", None)
    t.rating_speed = kw.get("rating_speed", None)
    cat = MagicMock()
    cat.name = kw.get("category_name", "Eléctrico")
    t.category = cat
    req = MagicMock()
    req.full_name = kw.get("requester_name", "JUAN PEREZ")
    t.requester = req
    t.active_technicians = kw.get("active_technicians", [])
    t.technicians = kw.get("technicians", [])
    return t


def _tech_assignment(user_id, unassigned_at=None):
    a = MagicMock()
    a.user_id = user_id
    a.unassigned_at = unassigned_at
    return a


# ─────────────────────────────────────────────────────────────────────
# URL anchors
# ─────────────────────────────────────────────────────────────────────

class TestNotificationURLAnchors:
    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_resolved_url_has_resolution_anchor(self, mock_bc, mock_create):
        ticket = _fake_ticket(id=42, status="RESOLVED_SUCCESS")
        db = MagicMock()
        MaintNotificationHelper.notify_ticket_resolved(db, ticket)

        assert mock_create.called
        call = mock_create.call_args
        url = call.kwargs["data"]["url"]
        assert url == "/maintenance/tickets/42#resolution"

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_comment_url_has_comments_anchor(self, mock_bc, mock_create):
        ticket = _fake_ticket(
            id=15,
            status="IN_PROGRESS",
            active_technicians=[_tech_assignment(20)],
        )
        comment = MagicMock()
        comment.content = "Listo"
        comment.is_internal = False
        author_id = 99

        db = MagicMock()
        author = MagicMock(full_name="ANA LOPEZ")
        db.get.return_value = author

        MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id)

        # Recipientes: requester (100) + tech 20, sin author
        urls = [c.kwargs["data"]["url"] for c in mock_create.call_args_list]
        for url in urls:
            assert url == "/maintenance/tickets/15#comments"

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_assigned_url_no_anchor(self, mock_bc, mock_create):
        ticket = _fake_ticket(id=8, status="ASSIGNED")
        db = MagicMock()
        tech = MagicMock(full_name="LUIS MARTIN")
        db.get.return_value = tech

        MaintNotificationHelper.notify_technician_assigned(db, ticket, technician_id=33)

        url = mock_create.call_args.kwargs["data"]["url"]
        assert url == "/maintenance/tickets/8"

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_rated_url_has_resolution_anchor(self, mock_bc, mock_create):
        """notify_ticket_rated debe enviar al técnico con anchor #resolution."""
        ticket = _fake_ticket(
            id=11,
            status="CLOSED",
            rating_attention=5,
            rating_speed=4,
            active_technicians=[_tech_assignment(77)],
        )
        db = MagicMock()
        db.get.return_value = MagicMock(full_name="ROSA CRUZ")

        MaintNotificationHelper.notify_ticket_rated(db, ticket)

        urls = [c.kwargs["data"]["url"] for c in mock_create.call_args_list]
        # Al menos un recipient debe haberse notificado con anchor correcto
        assert any(u == "/maintenance/tickets/11#resolution" for u in urls)


# ─────────────────────────────────────────────────────────────────────
# Dedup de recipientes
# ─────────────────────────────────────────────────────────────────────

class TestNotificationDedup:
    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_comment_excludes_author(self, mock_bc, mock_create):
        author_id = 100  # mismo que requester
        ticket = _fake_ticket(
            id=1,
            requester_id=100,
            active_technicians=[_tech_assignment(20), _tech_assignment(30)],
        )
        comment = MagicMock(content="Test", is_internal=False)
        db = MagicMock()
        db.get.return_value = MagicMock(full_name="REQUESTER")

        MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id)

        recipients = [c.kwargs["user_id"] for c in mock_create.call_args_list]
        assert author_id not in recipients
        assert set(recipients) == {20, 30}

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_internal_comment_skips_requester(self, mock_bc, mock_create):
        """Comentarios internos no llegan al solicitante."""
        ticket = _fake_ticket(
            id=1,
            requester_id=100,
            active_technicians=[_tech_assignment(20)],
        )
        comment = MagicMock(content="Nota interna", is_internal=True)
        db = MagicMock()
        db.get.return_value = MagicMock(full_name="TECH")

        MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id=20)

        recipients = [c.kwargs["user_id"] for c in mock_create.call_args_list]
        assert 100 not in recipients  # requester excluido
