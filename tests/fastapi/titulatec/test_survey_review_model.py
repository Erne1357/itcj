"""Contrato de ESQUEMA de `titulatec_survey_reviews` (Tarea 1, liberacion GTV).

`Base.metadata` solo dice lo que el codigo CREE que existe. Este archivo golpea
Postgres de verdad con `db_session`: si la migracion no corrio, el primer
INSERT truena con `UndefinedTable`/`ProgrammingError`, que es justo el fallo
que hay que ver antes de escribir la migracion (patron de
`test_survey_models_schema.py`).

Cubre solo el MODELO y sus constraints de fila: unique de proceso, FKs
(incluido el tipo BigInteger de `response_id`/`reviewed_by_id`), default del
`status` e indices con el nombre exacto que otras tareas van a referenciar. El
service (`SurveyReviewService`) y sus reglas de transicion son tarea aparte.

Construye la respuesta minima a mano en vez de depender de
`make_survey_review` (fixture de la Tarea 2, que ademas siembra una solicitud
COMPLETA): este archivo quiere aislar la fila de `titulatec_survey_reviews`
por si misma.

Patron para las violaciones de constraint: `with db_session.begin_nested():`.
Un `db_session.rollback()` pelado descarta tambien las filas que sembraron las
fixtures (ver conftest, `join_transaction_mode="create_savepoint"`); el
savepoint anidado solo descarta el INSERT que fallo.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import BigInteger
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError


def _uniq() -> str:
    return uuid.uuid4().hex[:8]


def _survey_response(db, *, process, user):
    """Formulario + respuesta minimos, suficientes para colgar una solicitud."""
    from itcj2.apps.titulatec.models import SurveyForm, SurveyResponse

    form = SurveyForm(
        code=f"prueba_review_{_uniq()}",
        version=1,
        status="open",
        title="Encuesta de egresados (prueba review)",
        schema={"enabled": True, "fields": []},
    )
    db.add(form)
    db.flush()

    resp = SurveyResponse(
        form_id=form.id, form_version=form.version,
        user_id=user.id, process_id=process.id,
        identity_source="session",
        control_number=user.control_number,
        answers={"situacion_laboral": "empleado"},
    )
    db.add(resp)
    db.flush()
    return resp


# ---------------------------------------------------------------------------
# Registro (no tocan la BD)
# ---------------------------------------------------------------------------
def test_tabla_esta_en_base_metadata():
    """Sin el re-export en `models/__init__.py`, el siguiente autogenerate
    emite `drop_table` y el `create_all` del CI no la crea."""
    import itcj2.apps.titulatec.models  # noqa: F401
    from itcj2.models.base import Base

    assert "titulatec_survey_reviews" in Base.metadata.tables


def test_survey_review_esta_reexportado_en_all():
    import itcj2.apps.titulatec.models as models

    assert hasattr(models, "SurveyReview")
    assert "SurveyReview" in models.__all__


# ---------------------------------------------------------------------------
# Columnas y defaults
# ---------------------------------------------------------------------------
def test_round_trip_con_defaults(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    proc = make_process(student)
    resp = _survey_response(db_session, process=proc, user=student)

    review = SurveyReview(process_id=proc.id, response_id=resp.id)
    db_session.add(review)
    db_session.flush()

    assert review.status == "in_review"          # server_default
    assert review.rejection_reason is None
    assert review.reviewed_by_id is None
    assert review.reviewed_at is None
    assert review.submitted_at is not None
    assert review.created_at is not None
    assert review.updated_at is not None


def test_dictamen_se_guarda_con_reviewer_y_motivo(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    officer = make_user(first_name="GTV")
    proc = make_process(student)
    resp = _survey_response(db_session, process=proc, user=student)

    review = SurveyReview(
        process_id=proc.id, response_id=resp.id, status="rejected",
        rejection_reason="Pendiente en Residencias, acude a Servicio Externo.",
        reviewed_by_id=officer.id,
    )
    db_session.add(review)
    db_session.flush()

    assert review.status == "rejected"
    assert review.reviewed_by_id == officer.id
    assert review.rejection_reason.startswith("Pendiente")


# ---------------------------------------------------------------------------
# Unique: una solicitud por proceso
# ---------------------------------------------------------------------------
def test_process_id_es_unico(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    proc = make_process(student)
    resp1 = _survey_response(db_session, process=proc, user=student)
    resp2 = _survey_response(db_session, process=proc, user=student)

    db_session.add(SurveyReview(process_id=proc.id, response_id=resp1.id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyReview(process_id=proc.id, response_id=resp2.id))
            db_session.flush()


def test_uq_lleva_el_nombre_del_spec(db_session):
    """El nombre exacto lo exige el brief: otras tareas (service, rutas) lo
    dan por sentado en sus propios mensajes de error."""
    row = db_session.execute(sa_text(
        "SELECT conname FROM pg_constraint "
        "WHERE conname = 'uq_titulatec_survey_reviews_process'"
    )).first()
    assert row is not None


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------
def test_process_id_referencia_titulatec_processes(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    proc = make_process(student)
    resp = _survey_response(db_session, process=proc, user=student)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyReview(process_id=999_999_999, response_id=resp.id))
            db_session.flush()


def test_response_id_es_bigint_y_referencia_survey_responses(
        db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    assert isinstance(SurveyReview.__table__.c.response_id.type, BigInteger)

    student = make_user()
    proc = make_process(student)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyReview(process_id=proc.id,
                                        response_id=999_999_999_999))
            db_session.flush()


def test_reviewed_by_id_es_bigint_y_referencia_core_users(
        db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    assert isinstance(SurveyReview.__table__.c.reviewed_by_id.type, BigInteger)

    student = make_user()
    proc = make_process(student)
    resp = _survey_response(db_session, process=proc, user=student)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyReview(
                process_id=proc.id, response_id=resp.id,
                reviewed_by_id=999_999_999,
            ))
            db_session.flush()


# ---------------------------------------------------------------------------
# Indices (nombre exacto: la migracion y el brief los fijan)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("index_name", [
    "ix_titulatec_survey_reviews_status",
    "ix_titulatec_survey_reviews_response_id",
])
def test_indices_con_nombre_exacto(db_session, index_name):
    row = db_session.execute(sa_text(
        "SELECT indexname FROM pg_indexes WHERE indexname = :n"
    ), {"n": index_name}).first()
    assert row is not None, f"falta el indice {index_name}"
