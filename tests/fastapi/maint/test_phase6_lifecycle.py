"""
M13 — Suite de ciclo de vida de un ticket de mantenimiento.

Cubre el camino feliz completo (ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED)
y los guards de cada transición a nivel servicio, con el patrón MagicMock-DB.

Complementa:
- test_phase0_hotfixes.py — gate D-F de resolve (ASSIGNED directo).
- test_phase1_coordinator_flow.py — assign (H1) / unassign (H2) / route (M5).
- test_routing.py — route-targets + enrutado.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import itcj2.models  # noqa: F401
from itcj2.apps.maint.services import ticket_service


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _tech(user_id, unassigned_at=None):
    return SimpleNamespace(user_id=user_id, unassigned_at=unassigned_at)


def _ticket(status, **kw):
    """Ticket mutable mínimo para ejercitar las transiciones del servicio."""
    return SimpleNamespace(
        id=kw.get("id", 1),
        ticket_number="MANT-2026-000001",
        status=status,
        requester_id=kw.get("requester_id", 100),
        technicians=kw.get("technicians", []),
        category=kw.get("category", None),
        rating_attention=kw.get("rating_attention", None),
        rating_speed=None,
        rating_efficiency=None,
        rating_comment=None,
        rated_at=None,
        closed_at=None,
        updated_at=None,
        updated_by_id=None,
    )


def _db_for(ticket):
    db = MagicMock()
    db.get.return_value = ticket
    return db


_CATALOG = (
    "itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes",
    "itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes",
)


# ─────────────────────────────────────────────────────────────────────
# start_progress
# ─────────────────────────────────────────────────────────────────────

class TestStartProgress:
    def test_active_tech_starts(self):
        ticket = _ticket("ASSIGNED", technicians=[_tech(20)])
        db = _db_for(ticket)
        result = ticket_service.start_progress(db, 1, user_id=20, user_roles=["tech_maint"])
        assert result.status == "IN_PROGRESS"
        db.commit.assert_called_once()

    def test_cannot_start_from_non_assigned(self):
        ticket = _ticket("IN_PROGRESS", technicians=[_tech(20)])
        db = _db_for(ticket)
        with pytest.raises(HTTPException) as exc:
            ticket_service.start_progress(db, 1, user_id=20, user_roles=["tech_maint"])
        assert exc.value.status_code == 400
        db.commit.assert_not_called()

    def test_unrelated_user_cannot_start(self):
        ticket = _ticket("ASSIGNED", technicians=[_tech(20)], category=None)
        db = _db_for(ticket)
        with pytest.raises(HTTPException) as exc:
            ticket_service.start_progress(db, 1, user_id=999, user_roles=["staff"])
        assert exc.value.status_code == 403

    def test_dispatcher_can_start_unassigned(self):
        ticket = _ticket("ASSIGNED", technicians=[])
        db = _db_for(ticket)
        result = ticket_service.start_progress(db, 1, user_id=7674, user_roles=["dispatcher"])
        assert result.status == "IN_PROGRESS"


# ─────────────────────────────────────────────────────────────────────
# rate_ticket
# ─────────────────────────────────────────────────────────────────────

class TestRate:
    def _rate(self, db, requester_id=100):
        return ticket_service.rate_ticket(
            db, ticket_id=1, requester_id=requester_id,
            rating_attention=5, rating_speed=4, rating_efficiency=True,
            comment="Excelente",
        )

    def test_requester_rates_resolved_ticket(self):
        ticket = _ticket("RESOLVED_SUCCESS", requester_id=100)
        db = _db_for(ticket)
        result = self._rate(db)
        assert result.status == "CLOSED"
        assert result.rating_attention == 5
        db.commit.assert_called_once()

    def test_only_requester_can_rate(self):
        ticket = _ticket("RESOLVED_SUCCESS", requester_id=100)
        db = _db_for(ticket)
        with pytest.raises(HTTPException) as exc:
            self._rate(db, requester_id=200)
        assert exc.value.status_code == 403
        db.commit.assert_not_called()

    def test_cannot_rate_unresolved(self):
        ticket = _ticket("IN_PROGRESS", requester_id=100)
        db = _db_for(ticket)
        with pytest.raises(HTTPException) as exc:
            self._rate(db)
        assert exc.value.status_code == 400

    def test_cannot_rate_twice(self):
        ticket = _ticket("RESOLVED_SUCCESS", requester_id=100, rating_attention=3)
        db = _db_for(ticket)
        with pytest.raises(HTTPException) as exc:
            self._rate(db)
        assert exc.value.status_code == 400
        assert "ya fue calificado" in exc.value.detail.lower()


# ─────────────────────────────────────────────────────────────────────
# Camino feliz completo: ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
# ─────────────────────────────────────────────────────────────────────

class TestFullLifecycle:
    @patch(_CATALOG[1])
    @patch(_CATALOG[0])
    def test_assigned_to_closed(self, mock_types, mock_origins):
        mock_types.return_value = {"PREVENTIVO", "CORRECTIVO"}
        mock_origins.return_value = {"INTERNO", "EXTERNO"}

        ticket = _ticket("ASSIGNED", requester_id=100, technicians=[_tech(20)])
        db = _db_for(ticket)

        # 1) técnico inicia
        ticket_service.start_progress(db, 1, user_id=20, user_roles=["tech_maint"])
        assert ticket.status == "IN_PROGRESS"

        # 2) técnico resuelve (vía normal, no fast-resolver)
        resolved, warnings = ticket_service.resolve_ticket(
            db=db, ticket_id=1, resolved_by_id=20, success=True,
            maintenance_type="PREVENTIVO", service_origin="INTERNO",
            resolution_notes="ok", time_invested_minutes=30,
            is_fast_resolver=False,
        )
        assert resolved.status == "RESOLVED_SUCCESS"

        # 3) solicitante califica → CLOSED
        closed = ticket_service.rate_ticket(
            db, ticket_id=1, requester_id=100,
            rating_attention=5, rating_speed=5, rating_efficiency=True,
        )
        assert closed.status == "CLOSED"
        assert closed.rated_at is not None
