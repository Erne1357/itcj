"""Elegibilidad para cotejo = 3 documentos iniciales aprobados."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.document_service import DocumentService

INITIAL = ["birth_certificate", "high_school_cert", "curp"]


def _doc(status):
    return SimpleNamespace(review_status=status)


@patch("itcj2.apps.titulatec.services.document_service.DocumentService.get_document")
def test_all_approved_true(mock_get):
    mock_get.side_effect = lambda db, pid, code: _doc("approved")
    assert DocumentService.initial_docs_all_approved(MagicMock(), 1) is True


@patch("itcj2.apps.titulatec.services.document_service.DocumentService.get_document")
def test_one_missing_false(mock_get):
    mapping = {"birth_certificate": _doc("approved"), "high_school_cert": _doc("approved"), "curp": None}
    mock_get.side_effect = lambda db, pid, code: mapping[code]
    assert DocumentService.initial_docs_all_approved(MagicMock(), 1) is False


@patch("itcj2.apps.titulatec.services.document_service.DocumentService.get_document")
def test_one_rejected_false(mock_get):
    mapping = {"birth_certificate": _doc("approved"), "high_school_cert": _doc("rejected"), "curp": _doc("approved")}
    mock_get.side_effect = lambda db, pid, code: mapping[code]
    assert DocumentService.initial_docs_all_approved(MagicMock(), 1) is False
