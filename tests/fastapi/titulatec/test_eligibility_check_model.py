"""Contrato de `titulatec_eligibility_checks` y las dos columnas que la enlazan
(`EnrollmentRequest.last_check_id`, `Cohort.sii_auto_approve`).

Solo modelo + migracion (Tarea 3 del plan de elegibilidad SII): no hay
service todavia, asi que las filas aqui se arman a mano, como
`test_review_window_model.py` hace con `IntegrityError` bajo
`begin_nested()`.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest


@pytest.fixture()
def solicitud(db_session, make_cohort):
    """Una `EnrollmentRequest` minima, para colgarle checks."""
    cohort = make_cohort()
    req = EnrollmentRequest(
        cohort_id=cohort.id,
        control_number="20221234",
        first_name="Ana",
        last_name="Martinez",
        phone="6560000000",
        contact_email="ana@example.com",
        has_efirma=False,
        kind="unknown",
    )
    db_session.add(req)
    db_session.flush()
    return {"cohort": cohort, "req": req}


def test_el_check_nace_pending_con_intento_1_y_started_at(db_session, solicitud):
    chk = EligibilityCheck(request_id=solicitud["req"].id)
    db_session.add(chk)
    db_session.flush()

    assert chk.id is not None
    assert chk.status == "pending"
    assert chk.attempt == 1
    assert chk.started_at is not None
    assert chk.finished_at is None
    assert chk.duration_ms is None


def test_el_check_guarda_resultados_facts_y_version_de_reglas(db_session, solicitud):
    chk = EligibilityCheck(
        request_id=solicitud["req"].id,
        status="apt",
        rules_version="2026-09-25.1",
        results=[{"rule": "existe", "ok": True, "message": None}],
        facts={"estatus": "activo", "creditos_aprobados": 300},
        attempt=2,
    )
    db_session.add(chk)
    db_session.flush()
    db_session.refresh(chk)

    assert chk.results == [{"rule": "existe", "ok": True, "message": None}]
    assert chk.facts == {"estatus": "activo", "creditos_aprobados": 300}
    assert chk.rules_version == "2026-09-25.1"
    assert chk.attempt == 2


def test_el_check_conoce_su_solicitud(db_session, solicitud):
    chk = EligibilityCheck(request_id=solicitud["req"].id)
    db_session.add(chk)
    db_session.flush()
    db_session.refresh(chk)

    assert chk.request is solicitud["req"]


def test_request_id_es_obligatorio(db_session, solicitud):
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(EligibilityCheck())
            db_session.flush()


def test_request_id_exige_una_solicitud_existente(db_session, solicitud):
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(EligibilityCheck(request_id=9_999_999_999))
            db_session.flush()


def test_la_solicitud_apunta_a_su_check_vigente(db_session, solicitud):
    chk = EligibilityCheck(request_id=solicitud["req"].id, status="apt")
    db_session.add(chk)
    db_session.flush()

    solicitud["req"].last_check_id = chk.id
    db_session.flush()
    db_session.refresh(solicitud["req"])

    assert solicitud["req"].last_check_id == chk.id


def test_last_check_id_nace_nulo(db_session, solicitud):
    assert solicitud["req"].last_check_id is None


def test_la_convocatoria_nace_con_auto_approve_encendido(db_session, make_cohort):
    cohort = make_cohort()
    db_session.flush()
    db_session.refresh(cohort)

    assert cohort.sii_auto_approve is True


def test_sii_auto_approve_se_puede_apagar(db_session, make_cohort):
    cohort = make_cohort()
    cohort.sii_auto_approve = False
    db_session.flush()
    db_session.refresh(cohort)

    assert cohort.sii_auto_approve is False
