"""Contrato de ESQUEMA del no adeudo de biblioteca y las constancias por lote
(Tarea 1, spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.1).

Golpea Postgres de verdad con `db_session` (patrón de `test_survey_review_model.py`
/ `test_review_window_model.py`): si la migración `tt20261001a` no corrió, el
primer INSERT truena con `UndefinedTable`, que es justo el fallo que hay que
ver antes de escribir la migración.

Cubre SOLO el modelo y sus constraints de fila: tablas, defaults, UNIQUE,
CHECK de dinero, nullability y las fixtures nuevas (`make_library_clearance`,
`make_process(..., library_clearance=...)`, `make_cohort(...,
book_donation_amount=...)`). Los servicios (`LibraryClearanceService`,
`CertificateService`, `ClearanceGate`) son tareas aparte.

Patrón para violaciones de constraint: `with db_session.begin_nested():` —
un `db_session.rollback()` pelado descarta también las filas que sembraron
las fixtures (`join_transaction_mode="create_savepoint"`).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

from itcj2.models.base import Base


# ---------------------------------------------------------------------------
# Registro: tablas y re-exports
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tabla", [
    "titulatec_library_clearances",
    "titulatec_certificates",
    "titulatec_certificate_batches",
    "titulatec_certificate_counters",
    "titulatec_prior_clearances",
])
def test_las_5_tablas_estan_en_base_metadata(tabla):
    import itcj2.apps.titulatec.models  # noqa: F401

    assert tabla in Base.metadata.tables


@pytest.mark.parametrize("nombre", [
    "LibraryClearance", "Certificate", "CertificateBatch",
    "CertificateCounter", "PriorClearance",
])
def test_los_5_modelos_estan_reexportados_en_all(nombre):
    import itcj2.apps.titulatec.models as models

    assert hasattr(models, nombre)
    assert nombre in models.__all__


def test_dominios_de_modulo_son_los_del_brief():
    from itcj2.apps.titulatec.models.library_clearance import (
        CLEARED_VIA, LIBRARY_STATUSES,
    )
    from itcj2.apps.titulatec.models.certificate import CERTIFICATE_KINDS
    from itcj2.apps.titulatec.models.prior_clearance import PRIOR_KINDS
    from itcj2.apps.titulatec.models.survey_review import SURVEY_REVIEW_ORIGINS

    assert LIBRARY_STATUSES == ("pending", "awaiting_payment", "cleared")
    assert CLEARED_VIA == ("payment", "no_charge", "prior", "legacy")
    assert CERTIFICATE_KINDS == ("survey_release", "library_clearance")
    assert PRIOR_KINDS == ("survey", "library")
    assert SURVEY_REVIEW_ORIGINS == ("submission", "prior")


# ---------------------------------------------------------------------------
# LibraryClearance
# ---------------------------------------------------------------------------
@pytest.fixture()
def egresado(make_user, make_process):
    """Un proceso SIN la fila de no adeudo (para probar la tabla aislada)."""
    student = make_user()
    process = make_process(student, library_clearance=None)
    return {"student": student, "process": process}


def test_nace_pending_sin_cleared_via_ni_montos(db_session, egresado):
    from itcj2.apps.titulatec.models import LibraryClearance

    row = LibraryClearance(process_id=egresado["process"].id)
    db_session.add(row)
    db_session.flush()

    assert row.id is not None
    assert row.status == "pending"
    assert row.cleared_via is None
    assert row.debt_amount is None
    assert row.donation_amount is None
    assert row.total_amount is None
    assert row.created_at is not None
    assert row.updated_at is not None


def test_acepta_montos_congruentes(db_session, egresado):
    from itcj2.apps.titulatec.models import LibraryClearance

    row = LibraryClearance(
        process_id=egresado["process"].id, status="awaiting_payment",
        debt_amount=Decimal("500.00"), donation_amount=Decimal("300.00"),
        total_amount=Decimal("800.00"),
    )
    db_session.add(row)
    db_session.flush()

    assert row.total_amount == Decimal("800.00")


def test_process_id_es_unico(db_session, egresado):
    from itcj2.apps.titulatec.models import LibraryClearance

    db_session.add(LibraryClearance(process_id=egresado["process"].id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(LibraryClearance(process_id=egresado["process"].id))
            db_session.flush()


def test_uq_lleva_el_nombre_del_brief(db_session):
    row = db_session.execute(sa_text(
        "SELECT conname FROM pg_constraint "
        "WHERE conname = 'uq_titulatec_library_clearances_process'"
    )).first()
    assert row is not None


def test_process_id_referencia_titulatec_processes(db_session):
    from itcj2.apps.titulatec.models import LibraryClearance

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(LibraryClearance(process_id=999_999_999))
            db_session.flush()


def test_library_by_id_paid_by_id_prior_by_id_son_bigint(db_session):
    from itcj2.apps.titulatec.models import LibraryClearance

    cols = LibraryClearance.__table__.c
    assert isinstance(cols["library_by_id"].type, BigInteger)
    assert isinstance(cols["paid_by_id"].type, BigInteger)
    assert isinstance(cols["prior_by_id"].type, BigInteger)


@pytest.mark.parametrize("campo", ["debt_amount", "donation_amount", "total_amount"])
def test_montos_negativos_truenan(db_session, egresado, campo):
    from itcj2.apps.titulatec.models import LibraryClearance

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(LibraryClearance(
                process_id=egresado["process"].id,
                **{campo: Decimal("-5.00")},
            ))
            db_session.flush()


def test_total_distinto_de_la_suma_truena(db_session, egresado):
    from itcj2.apps.titulatec.models import LibraryClearance

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(LibraryClearance(
                process_id=egresado["process"].id,
                debt_amount=Decimal("500.00"), donation_amount=Decimal("300.00"),
                total_amount=Decimal("900.00"),
            ))
            db_session.flush()


# ---------------------------------------------------------------------------
# Cohort.book_donation_amount
# ---------------------------------------------------------------------------
def test_book_donation_amount_nace_null(db_session, make_cohort):
    cohort = make_cohort()
    assert cohort.book_donation_amount is None


def test_book_donation_amount_se_puede_fijar(db_session, make_cohort):
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    assert cohort.book_donation_amount == Decimal("800.00")


def test_book_donation_amount_negativo_truena(db_session, make_cohort):
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_cohort(book_donation_amount=Decimal("-1.00"))


def test_ck_book_donation_lleva_el_nombre_del_brief(db_session):
    row = db_session.execute(sa_text(
        "SELECT conname FROM pg_constraint "
        "WHERE conname = 'ck_titulatec_cohorts_book_donation'"
    )).first()
    assert row is not None


# ---------------------------------------------------------------------------
# Certificate / CertificateBatch / CertificateCounter
# ---------------------------------------------------------------------------
def _certificate_kwargs(process, **over):
    # `period_label` usa el FORMATO REAL del spec D7/§4.5 ("Agosto-Diciembre
    # 2026", 21 caracteres), no un placeholder corto: un placeholder de 5
    # caracteres (p. ej. "2029A") no habria distinguido String(20) de
    # String(40) y dejaba pasar en silencio una columna demasiado angosta
    # para el dato real que escribe `CertificateService.issue()` (Tarea 3).
    base = dict(
        kind="survey_release",
        number=f"GTV-2029-{over.pop('_n', 1):04d}",
        process_id=process.id,
        source_ref=f"survey_review:{process.id}",
        control_number="20290001",
        student_name="ALUMNO DE PRUEBA",
        program_name="Ingenieria de Pruebas",
        period_label="Agosto-Diciembre 2026",
        issued_by_id=process.student_id,
    )
    base.update(over)
    return base


def test_certificate_nace_con_issued_at_y_sin_lote_ni_anular(db_session, egresado):
    from itcj2.apps.titulatec.models import Certificate

    row = Certificate(**_certificate_kwargs(egresado["process"]))
    db_session.add(row)
    db_session.flush()

    assert row.id is not None
    assert row.issued_at is not None
    assert row.batch_id is None
    assert row.voided_at is None


@pytest.mark.parametrize("etiqueta", ["Agosto-Diciembre 2026", "Enero-Junio 2027"])
def test_certificate_period_label_acepta_etiquetas_reales_del_spec(
        db_session, egresado, etiqueta):
    """`period_label` debe caber el formato real de periodo (spec D7/§4.5),
    no solo el placeholder corto de `_certificate_kwargs`. "Agosto-Diciembre
    2026" mide 21 caracteres: con `String(20)` Postgres respondia
    `StringDataRightTruncation` en el camino normal de
    `CertificateService.issue()` (Tarea 3)."""
    from itcj2.apps.titulatec.models import Certificate

    # `_n` solo alimenta el folio de `_certificate_kwargs` (unicidad dentro de
    # este test parametrizado); `len(etiqueta)` basta porque las dos
    # etiquetas del spec miden distinto (21 y 16).
    kwargs = _certificate_kwargs(egresado["process"], period_label=etiqueta,
                                 _n=len(etiqueta))
    row = Certificate(**kwargs)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    assert row.period_label == etiqueta
    assert len(etiqueta) <= 40


def test_certificate_number_es_unico(db_session, egresado):
    from itcj2.apps.titulatec.models import Certificate

    db_session.add(Certificate(**_certificate_kwargs(egresado["process"], number="GTV-2029-0099")))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Certificate(
                **_certificate_kwargs(egresado["process"], number="GTV-2029-0099")))
            db_session.flush()


def test_certificate_process_id_referencia_titulatec_processes(db_session, egresado):
    from itcj2.apps.titulatec.models import Certificate

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            kwargs = _certificate_kwargs(egresado["process"])
            kwargs["process_id"] = 999_999_999
            db_session.add(Certificate(**kwargs))
            db_session.flush()


def test_certificate_batch_id_referencia_certificate_batches(db_session, egresado):
    from itcj2.apps.titulatec.models import Certificate

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            kwargs = _certificate_kwargs(egresado["process"])
            kwargs["batch_id"] = 999_999_999
            db_session.add(Certificate(**kwargs))
            db_session.flush()


def test_certificate_se_puede_anular_sin_borrarse(db_session, egresado):
    from itcj2.core.utils.timezone import db_now
    from itcj2.apps.titulatec.models import Certificate

    row = Certificate(**_certificate_kwargs(egresado["process"]))
    db_session.add(row)
    db_session.flush()

    row.voided_at = db_now()
    row.voided_by_id = egresado["process"].student_id
    row.void_reason = "Emitida por error."
    db_session.flush()

    assert db_session.get(Certificate, row.id) is not None


def test_indice_parcial_por_imprimir_existe(db_session):
    row = db_session.execute(sa_text(
        "SELECT indexname FROM pg_indexes "
        "WHERE indexname = 'ix_titulatec_certificates_pending_print'"
    )).first()
    assert row is not None


def test_certificate_batch_se_crea_con_count(db_session, make_user):
    from itcj2.apps.titulatec.models import CertificateBatch

    actor = make_user(first_name="CAJA")
    batch = CertificateBatch(kind="library_clearance", created_by_id=actor.id, count=3)
    db_session.add(batch)
    db_session.flush()

    assert batch.id is not None
    assert batch.created_at is not None


def test_certificate_counter_pk_compuesta_kind_year(db_session):
    from itcj2.apps.titulatec.models import CertificateCounter

    db_session.add(CertificateCounter(kind="survey_release", year=2029, last_value=1))
    db_session.flush()
    # mismo kind, otro anio: convive sin chocar
    db_session.add(CertificateCounter(kind="survey_release", year=2030, last_value=0))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(CertificateCounter(kind="survey_release", year=2029, last_value=0))
            db_session.flush()


def test_certificate_counter_last_value_nace_en_cero(db_session):
    from itcj2.apps.titulatec.models import CertificateCounter

    row = CertificateCounter(kind="library_clearance", year=2031)
    db_session.add(row)
    db_session.flush()
    assert row.last_value == 0


# ---------------------------------------------------------------------------
# PriorClearance
# ---------------------------------------------------------------------------
def test_prior_clearance_issued_on_es_opcional(db_session):
    from itcj2.apps.titulatec.models import PriorClearance

    row = PriorClearance(kind="library", control_number="20290002",
                         source="respaldo_2026_09_17.xlsx", issued_on=None)
    db_session.add(row)
    db_session.flush()

    assert row.issued_on is None
    assert row.applied_process_id is None
    assert row.applied_at is None


def test_prior_clearance_unique_kind_control_number(db_session):
    from itcj2.apps.titulatec.models import PriorClearance

    db_session.add(PriorClearance(kind="survey", control_number="20290003",
                                  source="archivo.xlsx", issued_on=date(2025, 5, 1)))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(PriorClearance(kind="survey", control_number="20290003",
                                          source="otro.xlsx", issued_on=date(2025, 6, 1)))
            db_session.flush()


def test_prior_clearance_mismo_control_distinto_kind_convive(db_session):
    from itcj2.apps.titulatec.models import PriorClearance

    db_session.add(PriorClearance(kind="survey", control_number="20290004",
                                  source="archivo.xlsx"))
    db_session.add(PriorClearance(kind="library", control_number="20290004",
                                  source="archivo.xlsx"))
    db_session.flush()  # no debe tronar


def test_prior_clearance_applied_process_id_referencia_processes(db_session):
    from itcj2.apps.titulatec.models import PriorClearance

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(PriorClearance(
                kind="library", control_number="20290005", source="archivo.xlsx",
                applied_process_id=999_999_999,
            ))
            db_session.flush()


# ---------------------------------------------------------------------------
# SurveyReview: response_id nullable, origin, prior_issued_on
# ---------------------------------------------------------------------------
def test_response_id_admite_null(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    proc = make_process(student)
    review = SurveyReview(process_id=proc.id, response_id=None, status="approved",
                          origin="prior")
    db_session.add(review)
    db_session.flush()

    assert review.response_id is None
    assert review.origin == "prior"


def test_origin_nace_submission_por_default(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyForm, SurveyResponse, SurveyReview

    student = make_user()
    proc = make_process(student)
    form = SurveyForm(code="prueba_origin", version=1, status="open",
                      title="Encuesta", schema={"enabled": True, "fields": []})
    db_session.add(form)
    db_session.flush()
    resp = SurveyResponse(form_id=form.id, form_version=form.version,
                          user_id=student.id, process_id=proc.id,
                          identity_source="session", answers={})
    db_session.add(resp)
    db_session.flush()

    review = SurveyReview(process_id=proc.id, response_id=resp.id)
    db_session.add(review)
    db_session.flush()

    assert review.origin == "submission"
    assert review.prior_issued_on is None


def test_prior_issued_on_acepta_fecha(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import SurveyReview

    student = make_user()
    proc = make_process(student)
    review = SurveyReview(process_id=proc.id, response_id=None, status="approved",
                          origin="prior", prior_issued_on=date(2025, 3, 1))
    db_session.add(review)
    db_session.flush()

    assert review.prior_issued_on == date(2025, 3, 1)


# ---------------------------------------------------------------------------
# Fixtures nuevas: make_library_clearance / make_process / make_cohort
# ---------------------------------------------------------------------------
def test_make_library_clearance_default_pending(db_session, make_user, make_process,
                                                 make_library_clearance):
    student = make_user()
    proc = make_process(student, library_clearance=None)

    row = make_library_clearance(proc)

    assert row.status == "pending"
    assert row.cleared_via is None


def test_make_library_clearance_cleared_usa_legacy_por_default(
        db_session, make_user, make_process, make_library_clearance):
    student = make_user()
    proc = make_process(student, library_clearance=None)

    row = make_library_clearance(proc, status="cleared")

    assert row.status == "cleared"
    assert row.cleared_via == "legacy"


def test_make_library_clearance_respeta_cleared_via_explicito(
        db_session, make_user, make_process, make_library_clearance):
    student = make_user()
    proc = make_process(student, library_clearance=None)

    row = make_library_clearance(proc, status="cleared", cleared_via="payment")

    assert row.cleared_via == "payment"


def test_make_process_default_crea_fila_cleared_legacy(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import LibraryClearance

    student = make_user()
    proc = make_process(student)

    row = (db_session.query(LibraryClearance)
          .filter_by(process_id=proc.id).one())
    assert row.status == "cleared"
    assert row.cleared_via == "legacy"


def test_make_process_library_clearance_none_no_crea_fila(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import LibraryClearance

    student = make_user()
    proc = make_process(student, library_clearance=None)

    row = (db_session.query(LibraryClearance)
          .filter_by(process_id=proc.id).first())
    assert row is None


def test_make_process_library_clearance_pending(db_session, make_user, make_process):
    from itcj2.apps.titulatec.models import LibraryClearance

    student = make_user()
    proc = make_process(student, library_clearance="pending")

    row = (db_session.query(LibraryClearance)
          .filter_by(process_id=proc.id).one())
    assert row.status == "pending"
    assert row.cleared_via is None


def test_make_cohort_book_donation_amount_default_none(db_session, make_cohort):
    assert make_cohort().book_donation_amount is None


def test_make_cohort_book_donation_amount_explicito(db_session, make_cohort):
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    assert cohort.book_donation_amount == Decimal("800.00")
