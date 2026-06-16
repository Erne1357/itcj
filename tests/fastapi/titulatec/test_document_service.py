"""Tests de DocumentService.review — notificación al alumno cuando se rechaza."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.document_service import DocumentService


class TestReview:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechazo_notifica_al_alumno(self, mock_notify):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(student_id=7)

        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="rejected", note="Ilegible", reviewer_id=200)

        assert ok is True
        db.commit.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["type"] == "DOCUMENT_REJECTED"
        assert kwargs["phase_number"] == 1
        assert kwargs["body"] == "Ilegible"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_aprobacion_no_notifica(self, mock_notify):
        db = MagicMock()
        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="approved", note=None, reviewer_id=200)
        assert ok is True
        mock_notify.assert_not_called()

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_documento_inexistente_devuelve_false(self, mock_notify):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="rejected", note="x", reviewer_id=200)
        assert ok is False
        mock_notify.assert_not_called()
