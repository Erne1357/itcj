"""Columnas de revision/FIFO del Formato B (fase 3) y su fabrica de pruebas."""
from datetime import datetime


def test_columnas_de_revision_existen_y_tienen_defaults(
        db_session, make_student, make_process, make_modality, make_format_b):
    modality = make_modality()
    process = make_process(make_student(), modality=modality)

    fb = make_format_b(process, modality=modality)
    db_session.refresh(fb)

    assert fb.status == "draft"
    assert fb.submission_count == 0
    assert fb.submitted_at is None
    assert fb.review_observations is None
    assert fb.reviewed_by_id is None
    assert fb.reviewed_at is None
    assert fb.modality_id == modality.id
    assert fb.modality.code == modality.code


def test_make_format_b_acepta_campos(db_session, make_student, make_process, make_format_b):
    process = make_process(make_student())
    enviado = datetime(2026, 10, 1, 9, 30)

    fb = make_format_b(
        process, status="submitted", submitted_at=enviado, submission_count=2,
        project_name="Proyecto X", review_observations={"project_name": "falta"},
    )
    db_session.refresh(fb)

    assert fb.status == "submitted"
    assert fb.submitted_at == enviado
    assert fb.submission_count == 2
    assert fb.project_name == "Proyecto X"
    assert fb.review_observations == {"project_name": "falta"}
    assert fb.modality is None
