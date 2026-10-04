"""Elegibilidad para cotejo = 3 documentos iniciales aprobados.

Hasta la Tarea 7 (2026-10-04-titulatec-paginacion) estas tres pruebas
parcheaban `DocumentService.get_document` con un `db` `MagicMock`: desde que
`initial_docs_all_approved` delega en `initial_docs_approved_map` (una sola
consulta en lote, sin `get_document`) el parche ya no tocaba nada. Fijan lo
mismo contra filas reales.
"""
import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.document_service import DocumentService

INITIAL = ["birth_certificate", "high_school_cert", "curp"]


@pytest.fixture()
def proc(seed_phase_defs, seed_document_types, make_program, make_student, make_process):
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ing. Elegibilidad")
    return make_process(make_student(), program=prog, current_phase=1)


def test_all_approved_true(db_session, proc, make_document):
    for code in INITIAL:
        make_document(proc, type_code=code, review_status="approved")
    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is True


def test_one_missing_false(db_session, proc, make_document):
    for code in INITIAL[:2]:
        make_document(proc, type_code=code, review_status="approved")
    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is False


def test_one_rejected_false(db_session, proc, make_document):
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="rejected")
    make_document(proc, type_code="curp", review_status="approved")
    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is False
