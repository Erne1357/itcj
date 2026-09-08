"""Cuando la encuesta acredita el requisito de cotejo (seccion 6.3).

Se escribe cumplimiento si y solo si: hay sesion, el usuario tiene proceso
`active`/`on_hold`, la convocatoria de ESE proceso tiene un requisito activo con
`auto_source='graduate_survey'`, y no hay ya un cumplimiento para
`(process_id, requirement_id)`.

El requisito se crea a mano en cada test (no via `seed_defaults`) para que la
prueba diga exactamente que condicion esta ejerciendo.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.services.survey_service import (
    AUTO_SOURCE_SURVEY,
    SurveyService,
)

ENVIO_OK = {"situacion_laboral": "empleado", "relacion_carrera": "5"}


@pytest.fixture()
def requisito_automatico(db_session):
    """El requisito que la encuesta acredita, en la convocatoria que se le pase."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    def _make(cohort, auto_source=AUTO_SOURCE_SURVEY, is_active=True):
        row = CotejoRequirement(
            cohort_id=cohort.id, icon="clipboard-check",
            label="Encuesta de egresados",
            hint="Comprobante de haberla contestado.",
            order_index=0, is_required=True, is_active=is_active,
            code="graduate_survey", auto_source=auto_source,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


def test_acredita_a_un_alumno_con_proceso_activo(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico,
):
    from itcj2.apps.titulatec.models import RequirementFulfillment

    form = make_survey_form(code="tt_test_credito")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort, current_phase=1)
    req = requisito_automatico(cohort)

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert errors == {}
    assert credit == "credited"
    ful = (db_session.query(RequirementFulfillment)
           .filter_by(process_id=proc.id, requirement_id=req.id).one())
    assert ful.status == "fulfilled"
    assert ful.source == "system"
    assert ful.external_ref == f"survey_response:{response.id}"
    # La respuesta queda LIGADA al proceso y a su convocatoria: son las columnas
    # `proceso_id`/`convocatoria_id` del export y lo unico que permite cruzar una
    # respuesta con la generacion que la contesto.
    assert response.process_id == proc.id
    assert response.cohort_id == cohort.id


def test_submit_commitea_UNA_sola_vez_y_el_credito_va_DENTRO(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico, monkeypatch,
):
    """Seccion 4.4 paso 7: respuesta + filas + cumplimiento son UNA transaccion.

    No se puede comprobar mirando los datos: `db_session` corre con
    `join_transaction_mode="create_savepoint"`, asi que un `commit()` del service
    solo libera un savepoint y la sesion de la prueba sigue viendo TODO. Un
    commit de mas es invisible para cualquier asercion sobre filas. Por eso se
    espia `commit` en vez de deducirlo.

    Se registra, en cada commit, si el cumplimiento YA existe. Con un solo commit
    al final la lista es `[True]`. Si alguien commitea antes de acreditar, el
    primer commit ocurre con la respuesta escrita y SIN credito: la lista es
    `[False, True]` — y eso es exactamente el estado que quedaria en disco si el
    proceso muriera entre los dos, un requisito sin acreditar para un alumno que
    ya contesto (o, al reves, un credito sin respuesta que lo respalde).
    """
    from itcj2.apps.titulatec.models import RequirementFulfillment

    form = make_survey_form(code="tt_test_1commit")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)
    req = requisito_automatico(cohort)

    commits: list[bool] = []
    real_commit = db_session.commit

    def espia_commit():
        commits.append(
            db_session.query(RequirementFulfillment)
            .filter_by(process_id=proc.id, requirement_id=req.id).first() is not None)
        return real_commit()

    monkeypatch.setattr(db_session, "commit", espia_commit)

    _r, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "credited"
    assert commits == [True], commits


def test_acredita_en_fase_1_sin_haber_abierto_nunca_la_pagina_de_la_cita(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico,
):
    """Regresion de la siembra perezosa (seccion 5.2).

    `list_or_seed` solo se disparaba desde una pagina gateada por la fase 2. Un
    alumno en fase 1 que contesta la encuesta —el caso MAYORITARIO, porque la
    encuesta se promueve publicamente— no tenia requisitos que acreditar y el
    credito se perdia en silencio.
    """
    form = make_survey_form(code="tt_test_fase1")
    student = make_student()
    cohort = make_cohort()
    make_process(student, cohort=cohort, current_phase=1)
    requisito_automatico(cohort)

    _r, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "credited"


def test_no_acredita_sin_proceso(db_session, make_survey_form, make_student):
    form = make_survey_form(code="tt_test_sinproc")
    student = make_student()

    response, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "no_process"
    # Sin proceso no hay a que ligarla, pero la respuesta SI se guarda: la
    # encuesta vale para estadistica aunque no acredite nada.
    assert response is not None
    assert response.process_id is None
    assert response.cohort_id is None


def test_sin_requisito_automatico_devuelve_no_requirement(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico,
):
    """Mensaje DIFERENCIADO: si no, un fallo de la regla 3 es invisible."""
    form = make_survey_form(code="tt_test_sinreq")
    student = make_student()
    cohort = make_cohort()
    make_process(student, cohort=cohort)
    # La convocatoria tiene requisitos, pero ninguno automatico: `auto_requirement`
    # no siembra (ya hay filas) y no encuentra ninguno con `auto_source`.
    requisito_automatico(cohort, auto_source=None)

    _r, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "no_requirement"


def test_no_duplica_el_cumplimiento(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico,
):
    """UNIQUE (process_id, requirement_id): la segunda respuesta dice 'already'."""
    from itcj2.apps.titulatec.models import RequirementFulfillment

    form = make_survey_form(code="tt_test_dup")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)
    req = requisito_automatico(cohort)

    _r1, _e1, primero = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id, client_ip=None, user_agent=None)
    _r2, _e2, segundo = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id, client_ip=None, user_agent=None)

    assert (primero, segundo) == ("credited", "already")
    assert db_session.query(RequirementFulfillment).filter_by(
        process_id=proc.id, requirement_id=req.id).count() == 1


def test_un_proceso_on_hold_tambien_acredita(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    requisito_automatico,
):
    """D5: al cerrar su convocatoria el proceso pasa a `on_hold`, no muere."""
    form = make_survey_form(code="tt_test_hold")
    student = make_student()
    cohort = make_cohort(status="closed")
    make_process(student, cohort=cohort, status="on_hold")
    requisito_automatico(cohort)

    _r, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "credited"
