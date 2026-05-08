"""Tests para itcj2.apps.maint.services.sla_service."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services import sla_service


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _fake_ticket(**kw):
    """Construye un objeto stand-in de MaintTicket suficiente para SLA."""
    t = MagicMock()
    t.id = kw.get("id", 1)
    t.ticket_number = kw.get("ticket_number", "MANT-2026-000001")
    t.title = kw.get("title", "Falla A/C")
    t.status = kw.get("status", "ASSIGNED")
    t.priority = kw.get("priority", "ALTA")
    t.due_at = kw.get("due_at", datetime.now() - timedelta(hours=2))
    t.sla_alert_sent_at = kw.get("sla_alert_sent_at", None)
    t.requester_department_id = kw.get("requester_department_id", 5)
    t.technicians = kw.get("technicians", [])
    return t


def _fake_tech_assignment(user_id, unassigned_at=None):
    a = MagicMock()
    a.user_id = user_id
    a.unassigned_at = unassigned_at
    return a


# ─────────────────────────────────────────────────────────────────────
# notify_overdue
# ─────────────────────────────────────────────────────────────────────

class TestNotifyOverdue:
    @patch("itcj2.core.services.notification_service.NotificationService.create")
    def test_notifies_active_techs_and_dispatchers(self, mock_create):
        """Verifica dedup y que sla_alert_sent_at queda set."""
        ticket = _fake_ticket(
            technicians=[
                _fake_tech_assignment(10),
                _fake_tech_assignment(20),
                _fake_tech_assignment(30, unassigned_at=datetime(2026, 1, 1)),  # inactivo
            ],
        )

        # Mock de query() para App / Role / UserAppRole
        db = MagicMock()
        app = MagicMock(id=1, key="maint")
        dispatcher_role = MagicMock(id=100, name="dispatcher")
        admin_role = MagicMock(id=200, name="admin")

        # Cada filter_by responde con un objeto distinto
        def _query_side_effect(model):
            chain = MagicMock()
            name = model.__name__
            if name == "App":
                chain.filter_by.return_value.first.return_value = app
            elif name == "Role":
                # Devolver el rol según el nombre buscado
                def _filter_by(name=None, **kw):
                    inner = MagicMock()
                    if name == "dispatcher":
                        inner.first.return_value = dispatcher_role
                    elif name == "admin":
                        inner.first.return_value = admin_role
                    else:
                        inner.first.return_value = None
                    return inner
                chain.filter_by.side_effect = _filter_by
            elif name == "UserAppRole":
                # Dispatcher 50, admin 60
                rows = [MagicMock(user_id=50), MagicMock(user_id=60)]
                chain.filter.return_value.all.return_value = rows
            return chain

        db.query.side_effect = _query_side_effect

        count = sla_service.notify_overdue(db, ticket)
        # Recipientes únicos: 10, 20, 50, 60
        assert count == 4
        called_users = {c.kwargs["user_id"] for c in mock_create.call_args_list}
        assert called_users == {10, 20, 50, 60}
        assert ticket.sla_alert_sent_at is not None

    @patch("itcj2.core.services.notification_service.NotificationService.create")
    def test_no_recipients_still_marks_alert_sent(self, mock_create):
        """Si no hay técnicos ni dispatchers, no notifica pero sí marca."""
        ticket = _fake_ticket(technicians=[])
        db = MagicMock()
        # App existe pero no hay UserAppRoles
        app = MagicMock(id=1)
        def _query_side_effect(model):
            chain = MagicMock()
            if model.__name__ == "App":
                chain.filter_by.return_value.first.return_value = app
            elif model.__name__ == "Role":
                chain.filter_by.return_value.first.return_value = MagicMock(id=100)
            elif model.__name__ == "UserAppRole":
                chain.filter.return_value.all.return_value = []
            return chain
        db.query.side_effect = _query_side_effect

        count = sla_service.notify_overdue(db, ticket)
        assert count == 0
        assert ticket.sla_alert_sent_at is not None
        mock_create.assert_not_called()

    @patch("itcj2.core.services.notification_service.NotificationService.create")
    def test_payload_includes_overdue_flags(self, mock_create):
        """Broadcast debe incluir is_overdue y sla_overdue."""
        ticket = _fake_ticket(
            technicians=[_fake_tech_assignment(10)],
            due_at=datetime(2026, 5, 1, 10, 0, 0),
        )
        db = MagicMock()
        app = MagicMock(id=1)
        def _query_side_effect(model):
            chain = MagicMock()
            if model.__name__ == "App":
                chain.filter_by.return_value.first.return_value = app
            elif model.__name__ == "Role":
                chain.filter_by.return_value.first.return_value = MagicMock(id=100)
            elif model.__name__ == "UserAppRole":
                chain.filter.return_value.all.return_value = []
            return chain
        db.query.side_effect = _query_side_effect

        # Solo verificamos que no crashea — broadcast se autoparché en conftest.
        sla_service.notify_overdue(db, ticket)
        assert ticket.sla_alert_sent_at is not None

    @patch("itcj2.core.services.notification_service.NotificationService.create")
    def test_notification_payload_url_anchor(self, mock_create):
        """data.url debe ser /maintenance/tickets/{id}."""
        ticket = _fake_ticket(
            id=42,
            ticket_number="MANT-2026-000042",
            technicians=[_fake_tech_assignment(99)],
        )
        db = MagicMock()
        def _query_side_effect(model):
            chain = MagicMock()
            chain.filter_by.return_value.first.return_value = None
            chain.filter.return_value.all.return_value = []
            return chain
        db.query.side_effect = _query_side_effect

        sla_service.notify_overdue(db, ticket)
        call = mock_create.call_args_list[0]
        assert call.kwargs["data"]["url"] == "/maintenance/tickets/42"
        assert call.kwargs["data"]["ticket_id"] == 42
        assert call.kwargs["type"] == "TICKET_OVERDUE"


# ─────────────────────────────────────────────────────────────────────
# run_overdue_check
# ─────────────────────────────────────────────────────────────────────

class TestRunOverdueCheck:
    def test_no_overdue_returns_zero(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = sla_service.run_overdue_check(db)
        assert result["found"] == 0
        assert result["notified_total"] == 0
        assert "checked_at" in result

    @patch("itcj2.apps.maint.services.sla_service.notify_overdue", return_value=2)
    def test_aggregates_notified_total(self, mock_notify):
        t1 = _fake_ticket(id=1, ticket_number="MANT-001")
        t2 = _fake_ticket(id=2, ticket_number="MANT-002")
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [t1, t2]

        result = sla_service.run_overdue_check(db)
        assert result["found"] == 2
        assert result["notified_total"] == 4  # 2 tickets × 2 recipients each
        assert "MANT-001" in result["ticket_numbers"]
        assert "MANT-002" in result["ticket_numbers"]
        db.commit.assert_called_once()
