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
        assert url == "/maint/tickets/42#resolution"

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
            assert url == "/maint/tickets/15#comments"

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_assigned_url_no_anchor(self, mock_bc, mock_create):
        ticket = _fake_ticket(id=8, status="ASSIGNED")
        db = MagicMock()
        tech = MagicMock(full_name="LUIS MARTIN")
        db.get.return_value = tech

        MaintNotificationHelper.notify_technician_assigned(db, ticket, technician_id=33)

        url = mock_create.call_args.kwargs["data"]["url"]
        assert url == "/maint/tickets/8"

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
        assert any(u == "/maint/tickets/11#resolution" for u in urls)


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


# ─────────────────────────────────────────────────────────────────────
# H11 — el broadcast WS no filtra contenido interno hacia el room compartido
# ─────────────────────────────────────────────────────────────────────

class TestInternalCommentWSPayload:
    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.sockets.maint.broadcast_ticket_comment_added")
    def test_internal_comment_ws_payload_omits_preview(self, mock_bc, mock_async, mock_create):
        """H11: para comentarios internos el payload WS no lleva preview/autor
        (el room de ticket incluye al solicitante)."""
        ticket = _fake_ticket(id=1, requester_id=100,
                              active_technicians=[_tech_assignment(20)])
        comment = MagicMock(content="Dato sensible staff-only", is_internal=True, id=5)
        db = MagicMock()
        db.get.return_value = MagicMock(full_name="TECH")

        MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id=20)

        assert mock_bc.called
        payload = mock_bc.call_args.args[1]
        assert payload["is_internal"] is True
        assert "preview" not in payload
        assert "author_name" not in payload
        assert "Dato sensible" not in str(payload)

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.sockets.maint.broadcast_ticket_comment_added")
    def test_public_comment_ws_payload_includes_preview(self, mock_bc, mock_async, mock_create):
        """Un comentario público sí difunde preview + autor por WS."""
        ticket = _fake_ticket(id=1, requester_id=100,
                              active_technicians=[_tech_assignment(20)])
        comment = MagicMock(content="Hola a todos", is_internal=False, id=6)
        db = MagicMock()
        db.get.return_value = MagicMock(full_name="ANA")

        MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id=20)

        payload = mock_bc.call_args.args[1]
        assert payload["is_internal"] is False
        assert payload["preview"] == "Hola a todos"
        assert payload["author_name"] == "ANA"


# ─────────────────────────────────────────────────────────────────────
# M7 — la cancelación notifica al creador (salvo que él mismo cancele)
# ─────────────────────────────────────────────────────────────────────

class TestCancelNotifiesCreator:
    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_creator_notified_when_staff_cancels(self, mock_bc, mock_create):
        ticket = _fake_ticket(id=3, requester_id=100,
                              active_technicians=[_tech_assignment(20)])
        ticket.cancel_reason = "Duplicado"
        ticket.canceled_by_id = 7674  # un dispatcher, no el creador
        db = MagicMock()

        MaintNotificationHelper.notify_ticket_canceled(db, ticket)

        recipients = {c.kwargs["user_id"] for c in mock_create.call_args_list}
        assert 100 in recipients   # creador avisado
        assert 20 in recipients    # técnico avisado

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    def test_creator_not_notified_when_self_cancels(self, mock_bc, mock_create):
        ticket = _fake_ticket(id=3, requester_id=100, active_technicians=[])
        ticket.cancel_reason = "Ya no aplica"
        ticket.canceled_by_id = 100  # el propio creador
        db = MagicMock()

        MaintNotificationHelper.notify_ticket_canceled(db, ticket)

        recipients = {c.kwargs["user_id"] for c in mock_create.call_args_list}
        assert 100 not in recipients  # no auto-aviso


# ─────────────────────────────────────────────────────────────────────
# H7 — destinatarios de ticket_created por ROL incluyendo herencia por PUESTO
# ─────────────────────────────────────────────────────────────────────

class TestTicketCreatedRecipientsByPosition:
    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_uses_role_helper_with_position_inheritance(self, mock_helper, mock_bc, mock_create):
        # incluye un dispatcher por puesto (8285) que UserAppRole no captaría
        mock_helper.return_value = [8285, 7670]
        ticket = _fake_ticket(id=9, requester_id=100)
        db = MagicMock()

        MaintNotificationHelper.notify_ticket_created(db, ticket)

        mock_helper.assert_called_once()
        args = mock_helper.call_args.args
        assert args[1] == "maint"
        assert set(args[2]) == {"dispatcher", "admin"}
        recipients = {c.kwargs["user_id"] for c in mock_create.call_args_list}
        assert recipients == {8285, 7670}  # requester (100) no está en la lista
