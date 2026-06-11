"""
Regresión de Fase 1 (auditoría de producción maint) — flujo de coordinadores.

H1 — coordinadores asignables como ejecutores (assign_technicians).
H2 — guards en unassign: estado abierto + propiedad de enrutado.
M1 — al remover al último técnico de un ticket IN_PROGRESS, revierte a PENDING.
H6 — notify_ticket_routed crea notificación para el coordinador destino (y omite el auto-enrutado).

Estrategia de mock idéntica a test_routing.py (MagicMock DB).
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import itcj2.models  # noqa: F401
from itcj2.apps.maint.services.assignment_service import (
    assign_technicians,
    unassign_technician,
)
from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper


def _make_ticket(status, coordinator_id=None):
    t = MagicMock()
    t.id = 1
    t.ticket_number = "MANT-2026-000001"
    t.title = "Fuga en el laboratorio"
    t.status = status
    t.is_open = status not in ("CLOSED", "CANCELED")
    t.technicians = []
    t.coordinator_id = coordinator_id
    t.priority = "HIGH"
    t.category = None
    t.updated_at = None
    t.updated_by_id = None
    return t


def _make_user(user_id, full_name="User"):
    u = MagicMock()
    u.id = user_id
    u.full_name = full_name
    return u


def _make_active_assignment(assignment_id, user_id):
    a = MagicMock()
    a.id = assignment_id
    a.user_id = user_id
    a.unassigned_at = None
    return a


# ───────────────────────── H1: coordinador asignable ─────────────────────────

class TestCoordinatorAssignable:

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician",
           return_value=True)
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_general_coordinator_can_self_assign(self, mock_roles, _mock_can):
        """H1: un coordinador general puede asignarse a sí mismo (antes 400 'no es técnico')."""
        # roles del TARGET (el coordinador) — antes el set asignable era solo tech_maint/admin
        mock_roles.return_value = {"maint_general_coordinator"}

        db = MagicMock()
        ticket = _make_ticket("PENDING", coordinator_id=10)   # enrutado a sí mismo
        db.get.side_effect = [ticket, _make_user(10, "General")]

        result = assign_technicians(
            db=db, ticket_id=1, assigned_by_id=10, user_ids=[10],
            assigner_roles={"maint_general_coordinator"}, is_global_admin=False,
        )

        assert len(result) == 1
        assert ticket.status == "ASSIGNED"
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_plain_requester_still_rejected(self, mock_roles):
        """Un usuario sin rol de ejecutor sigue siendo rechazado (400)."""
        mock_roles.return_value = {"requester"}

        db = MagicMock()
        ticket = _make_ticket("PENDING", coordinator_id=None)
        db.get.side_effect = [ticket, _make_user(50, "Random")]

        with pytest.raises(HTTPException) as exc:
            assign_technicians(
                db=db, ticket_id=1, assigned_by_id=1, user_ids=[50],
                assigner_roles={"admin"}, is_global_admin=True,
            )
        assert exc.value.status_code == 400


# ───────────────────────── H2 + M1: unassign ─────────────────────────

class TestUnassignGuards:

    def test_unassign_blocked_on_closed_ticket(self):
        """H2: no se puede desasignar de un ticket cerrado → 400 (antes lo revertía a PENDING)."""
        db = MagicMock()
        db.get.return_value = _make_ticket("CLOSED")

        with pytest.raises(HTTPException) as exc:
            unassign_technician(
                db=db, ticket_id=1, unassigned_by_id=5, user_id=20,
                unassigner_roles={"dispatcher"},
            )
        assert exc.value.status_code == 400
        db.commit.assert_not_called()

    def test_coordinator_cannot_unassign_foreign_ticket(self):
        """H2: un coordinador no puede desasignar en un ticket que no está en su cola → 403."""
        db = MagicMock()
        db.get.return_value = _make_ticket("ASSIGNED", coordinator_id=99)  # de otro coordinador

        with pytest.raises(HTTPException) as exc:
            unassign_technician(
                db=db, ticket_id=1, unassigned_by_id=40, user_id=20,
                unassigner_roles={"maint_area_coordinator"},
            )
        assert exc.value.status_code == 403

    def test_unassign_last_tech_from_in_progress_reverts_pending(self):
        """M1: remover al último técnico de un ticket IN_PROGRESS lo revierte a PENDING."""
        db = MagicMock()
        ticket = _make_ticket("IN_PROGRESS")
        ticket.technicians = [_make_active_assignment(1, 20)]
        db.get.side_effect = [ticket, _make_user(20, "Tech")]

        unassign_technician(
            db=db, ticket_id=1, unassigned_by_id=5, user_id=20,
            unassigner_roles={"dispatcher"},
        )

        assert ticket.status == "PENDING"
        db.commit.assert_called_once()


# ───────────────────────── H6: notify_ticket_routed ─────────────────────────

class TestNotifyRouted:

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper.render_notification",
           return_value={"title": "t", "body": "b"})
    def test_creates_notification_for_target(self, _mock_render, mock_create):
        """H6: enrutar a un coordinador crea una notificación in-app para él."""
        db = MagicMock()
        db.get.return_value = _make_user(30, "Coord")
        ticket = _make_ticket("PENDING", coordinator_id=30)

        MaintNotificationHelper.notify_ticket_routed(
            db, ticket, coordinator_id=30, routed_by_id=5,
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["user_id"] == 30
        assert mock_create.call_args.kwargs["type"] == "TICKET_ROUTED"

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    def test_skips_self_route(self, mock_create):
        """H6: el auto-enrutado (coordinador se asigna a sí mismo) no genera notificación."""
        db = MagicMock()
        ticket = _make_ticket("PENDING", coordinator_id=7)

        MaintNotificationHelper.notify_ticket_routed(
            db, ticket, coordinator_id=7, routed_by_id=7,
        )

        mock_create.assert_not_called()
