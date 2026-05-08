"""Tests para itcj2.apps.maint.services.attachment_cleanup."""
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services import attachment_cleanup as cleanup
from itcj2.apps.maint.models.attachment import MaintAttachment


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

class _FakeTicket:
    def __init__(self, id, status, resolved_at=None, closed_at=None,
                 canceled_at=None, updated_at=None):
        self.id = id
        self.status = status
        self.resolved_at = resolved_at
        self.closed_at = closed_at
        self.canceled_at = canceled_at
        self.updated_at = updated_at or datetime(2026, 1, 1, 12, 0, 0)


def _mock_db_with_tickets_and_attachments(tickets, attachments_by_ticket):
    """
    Construye un mock que responde a:
      db.query(MaintTicket).filter(...).all()        → tickets
      db.query(MaintAttachment).filter_by(ticket_id=X, is_purged=False)
                               .filter(auto_delete_at IS NULL).all() → attachments
    """
    db = MagicMock()

    def _query_side_effect(model):
        # Mockeamos según la clase pedida
        chain = MagicMock()
        if model.__name__ == "MaintTicket":
            chain.filter.return_value.all.return_value = tickets
        else:  # MaintAttachment
            def _filter_by(**kwargs):
                ticket_id = kwargs.get("ticket_id")
                inner = MagicMock()
                inner.filter.return_value.all.return_value = attachments_by_ticket.get(ticket_id, [])
                return inner
            chain.filter_by.side_effect = _filter_by
        return chain

    db.query.side_effect = _query_side_effect
    return db


# ─────────────────────────────────────────────────────────────────────
# set_auto_delete_on_resolved_tickets
# ─────────────────────────────────────────────────────────────────────

class TestSetAutoDeleteOnResolved:
    def test_assigns_to_attachments_without_date(self):
        ticket = _FakeTicket(
            id=1,
            status="RESOLVED_SUCCESS",
            resolved_at=datetime(2026, 5, 1, 10, 0, 0),
            updated_at=datetime(2026, 5, 1, 11, 0, 0),
        )
        att = MagicMock(spec=MaintAttachment)
        att.auto_delete_at = None
        att.id = 1

        db = _mock_db_with_tickets_and_attachments(
            tickets=[ticket],
            attachments_by_ticket={1: [att]},
        )

        count = cleanup.set_auto_delete_on_resolved_tickets(db)
        assert count == 1
        # auto_delete_at = max date + 7 days (default)
        assert att.auto_delete_at is not None
        # Diferencia ~7 días desde resolved_at o updated_at
        assert att.auto_delete_at >= datetime(2026, 5, 8)
        db.commit.assert_called_once()

    def test_no_tickets_no_commit(self):
        db = _mock_db_with_tickets_and_attachments(tickets=[], attachments_by_ticket={})
        count = cleanup.set_auto_delete_on_resolved_tickets(db)
        assert count == 0
        db.commit.assert_not_called()

    def test_uses_max_of_dates(self):
        """Si hay resolved_at < canceled_at < updated_at, usa updated_at."""
        ticket = _FakeTicket(
            id=1,
            status="CLOSED",
            resolved_at=datetime(2026, 5, 1),
            canceled_at=None,
            closed_at=datetime(2026, 5, 5),
            updated_at=datetime(2026, 5, 10),
        )
        att = MagicMock(spec=MaintAttachment)
        att.auto_delete_at = None
        att.id = 99

        db = _mock_db_with_tickets_and_attachments(
            tickets=[ticket],
            attachments_by_ticket={1: [att]},
        )
        cleanup.set_auto_delete_on_resolved_tickets(db)

        # Debe usar updated_at (más reciente) + 7 días = 2026-05-17
        expected = datetime(2026, 5, 10) + timedelta(days=7)
        assert att.auto_delete_at == expected


# ─────────────────────────────────────────────────────────────────────
# cleanup_expired_attachments — preserva fila
# ─────────────────────────────────────────────────────────────────────

class TestCleanupExpired:
    def _make_attachment(self, filepath, auto_delete_at):
        att = MagicMock(spec=MaintAttachment)
        att.id = 1
        att.ticket_id = 1
        att.filepath = filepath
        att.auto_delete_at = auto_delete_at
        att.is_purged = False
        att.purged_at = None
        att.original_filename = os.path.basename(filepath) if filepath else "deleted"
        return att

    def test_purge_removes_file_and_preserves_row(self, tmp_path):
        # Crear archivo real para verificar que lo borra
        target = tmp_path / "evidencia.jpg"
        target.write_bytes(b"fake jpeg content")
        assert target.exists()

        att = self._make_attachment(
            filepath=str(target),
            auto_delete_at=datetime(2020, 1, 1),  # ya vencido
        )

        db = MagicMock()
        chain = db.query.return_value.filter.return_value
        chain.all.return_value = [att]

        count = cleanup.cleanup_expired_attachments(db)
        assert count == 1
        # Archivo eliminado
        assert not target.exists()
        # Fila preservada con flags
        assert att.is_purged is True
        assert att.purged_at is not None
        assert att.filepath is None
        db.commit.assert_called_once()

    def test_purge_handles_missing_file(self):
        att = self._make_attachment(
            filepath="/no/existe/file.jpg",
            auto_delete_at=datetime(2020, 1, 1),
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [att]

        # No debe crashear aunque el archivo no exista
        count = cleanup.cleanup_expired_attachments(db)
        assert count == 1
        assert att.is_purged is True

    def test_no_expired_no_commit(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        count = cleanup.cleanup_expired_attachments(db)
        assert count == 0
        db.commit.assert_not_called()

    def test_purged_loses_filepath(self, tmp_path):
        """Después de purga, filepath debe ser None (no apuntar a archivo borrado)."""
        target = tmp_path / "x.pdf"
        target.write_bytes(b"%PDF")

        att = self._make_attachment(
            filepath=str(target),
            auto_delete_at=datetime(2020, 1, 1),
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [att]

        cleanup.cleanup_expired_attachments(db)
        assert att.filepath is None
