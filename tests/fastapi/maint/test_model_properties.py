"""Tests para propiedades calculadas de modelos maint (sin tocar BD)."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Carga eager de mappers para evitar issues con relationships
import itcj2.models  # noqa: F401

from itcj2.apps.maint.models.ticket import MaintTicket, SLA_HOURS
from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician
from itcj2.apps.maint.models.attachment import MaintAttachment


def _make_ticket(**kw) -> MaintTicket:
    """Construye un MaintTicket en memoria sin guardar en BD."""
    technicians = kw.pop("_technicians", [])
    defaults = {
        "id": 1,
        "ticket_number": "MANT-2026-000001",
        "requester_id": 1,
        "requester_department_id": 1,
        "category_id": 1,
        "priority": "MEDIA",
        "title": "Test",
        "description": "Test desc",
        "status": "PENDING",
        "created_by_id": 1,
    }
    defaults.update(kw)
    t = MaintTicket(**defaults)
    # Bypass SQLAlchemy collection events: settear via __dict__ evita el
    # listener que requiere _sa_instance_state en cada elemento.
    t.__dict__["technicians"] = technicians
    return t


# ─────────────────────────────────────────────────────────────────────
# MaintTicket properties
# ─────────────────────────────────────────────────────────────────────

class TestTicketIsOpen:
    @pytest.mark.parametrize("status", [
        "PENDING", "ASSIGNED", "IN_PROGRESS",
        "RESOLVED_SUCCESS", "RESOLVED_FAILED",
    ])
    def test_open_states(self, status):
        t = _make_ticket(status=status)
        assert t.is_open is True

    @pytest.mark.parametrize("status", ["CLOSED", "CANCELED"])
    def test_closed_states(self, status):
        t = _make_ticket(status=status)
        assert t.is_open is False


class TestTicketIsResolved:
    @pytest.mark.parametrize("status", ["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"])
    def test_resolved_states(self, status):
        assert _make_ticket(status=status).is_resolved is True

    @pytest.mark.parametrize("status", ["PENDING", "ASSIGNED", "IN_PROGRESS", "CANCELED"])
    def test_not_resolved(self, status):
        assert _make_ticket(status=status).is_resolved is False


class TestCanBeRated:
    def test_resolved_without_rating(self):
        t = _make_ticket(status="RESOLVED_SUCCESS", rating_attention=None)
        assert t.can_be_rated is True

    def test_resolved_with_rating(self):
        t = _make_ticket(status="RESOLVED_SUCCESS", rating_attention=5)
        assert t.can_be_rated is False

    def test_pending_cannot_be_rated(self):
        t = _make_ticket(status="PENDING")
        assert t.can_be_rated is False


class TestProgressPct:
    @pytest.mark.parametrize("status,expected_pct", [
        ("PENDING", 10),
        ("ASSIGNED", 30),
        ("IN_PROGRESS", 60),
        ("RESOLVED_SUCCESS", 90),
        ("RESOLVED_FAILED", 85),
        ("CLOSED", 100),
        ("CANCELED", 0),
    ])
    def test_known_states(self, status, expected_pct):
        assert _make_ticket(status=status).progress_pct == expected_pct


class TestActiveTechnicians:
    def test_no_technicians(self):
        t = _make_ticket()
        assert t.active_technicians == []

    def test_filters_unassigned(self):
        active = MagicMock(spec=MaintTicketTechnician)
        active.unassigned_at = None
        active.user_id = 10

        inactive = MagicMock(spec=MaintTicketTechnician)
        inactive.unassigned_at = datetime(2026, 1, 1)
        inactive.user_id = 20

        t = _make_ticket(_technicians=[active, inactive])
        assigned = t.active_technicians
        assert len(assigned) == 1
        assert assigned[0].user_id == 10


# ─────────────────────────────────────────────────────────────────────
# SLA_HOURS
# ─────────────────────────────────────────────────────────────────────

class TestSLAHours:
    def test_all_priorities_present(self):
        assert set(SLA_HOURS.keys()) == {"BAJA", "MEDIA", "ALTA", "URGENTE"}

    def test_urgent_shortest(self):
        assert SLA_HOURS["URGENTE"] < SLA_HOURS["ALTA"]
        assert SLA_HOURS["ALTA"] < SLA_HOURS["MEDIA"]
        assert SLA_HOURS["MEDIA"] < SLA_HOURS["BAJA"]


# ─────────────────────────────────────────────────────────────────────
# MaintAttachment.to_dict
# ─────────────────────────────────────────────────────────────────────

class TestAttachmentToDict:
    def _make_att(self, **kw) -> MaintAttachment:
        defaults = {
            "id": 1,
            "ticket_id": 1,
            "uploaded_by_id": 100,
            "attachment_type": "ticket",
            "filename": "img.jpg",
            "original_filename": "Foto Original.jpg",
            "filepath": "/uploads/img.jpg",
            "mime_type": "image/jpeg",
            "file_size": 12345,
            "uploaded_at": datetime(2026, 5, 7, 10, 30, 0),
            "is_purged": False,
            "purged_at": None,
        }
        defaults.update(kw)
        att = MaintAttachment(**defaults)
        # uploaded_by relation no se carga sin sesión — mockeala
        att.uploaded_by = None
        return att

    def test_basic_serialization(self):
        d = self._make_att().to_dict()
        assert d["id"] == 1
        assert d["original_filename"] == "Foto Original.jpg"
        assert d["mime_type"] == "image/jpeg"
        assert d["is_purged"] is False
        assert d["purged_at"] is None

    def test_filepath_never_exposed(self):
        d = self._make_att().to_dict()
        assert "filepath" not in d, "filepath debe ocultarse siempre"

    def test_purged_includes_purged_at(self):
        att = self._make_att(
            is_purged=True,
            purged_at=datetime(2026, 5, 14, 12, 0, 0),
            filepath=None,
        )
        d = att.to_dict()
        assert d["is_purged"] is True
        assert d["purged_at"] == "2026-05-14T12:00:00"

    def test_uploaded_at_iso(self):
        d = self._make_att().to_dict()
        assert d["uploaded_at"] == "2026-05-07T10:30:00"
