"""Resolucion del formulario abierto y borradores del alumno (secciones 3.2, 3.5, 6.4).

Nivel SERVICIO: se llama a `SurveyService` con `db_session` directamente, sin
`client`. La ruta `/borrador` y su presupuesto de peticiones se prueban aparte.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.services.survey_service import (
    MAX_ANSWERS_JSON_BYTES,
    SURVEY_CODE,
    SurveyService,
)


def test_la_constante_del_codigo_es_la_del_contrato():
    assert SURVEY_CODE == "egresados"


def test_open_form_toma_la_version_abierta_mas_alta(db_session, make_survey_form):
    """Resolver canonico: `code` + `status='open'` + ORDER BY version DESC."""
    make_survey_form(code="tt_test_encuesta", version=1, status="closed")
    v2 = make_survey_form(code="tt_test_encuesta", version=2, status="open")

    assert SurveyService.open_form(db_session, "tt_test_encuesta").id == v2.id


def test_open_form_ignora_borradores_y_cerradas(db_session, make_survey_form):
    make_survey_form(code="tt_test_draft", version=1, status="draft")
    make_survey_form(code="tt_test_draft", version=2, status="closed")

    assert SurveyService.open_form(db_session, "tt_test_draft") is None


def test_open_form_de_un_codigo_inexistente_es_none(db_session):
    assert SurveyService.open_form(db_session, "no_existe_este_codigo") is None


def test_save_draft_crea_una_fila_y_luego_la_ACTUALIZA(db_session, make_survey_form,
                                                       make_student):
    """UNIQUE (form_id, user_id): UPDATE en sitio, sin historial (seccion 3.5)."""
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(code="tt_test_borrador")
    student = make_student()

    primero = SurveyService.save_draft(db_session, form.id, student.id,
                                       {"situacion_laboral": "buscando"})
    segundo = SurveyService.save_draft(db_session, form.id, student.id,
                                       {"situacion_laboral": "empleado"})

    assert primero.id == segundo.id
    filas = db_session.query(SurveyDraft).filter_by(form_id=form.id,
                                                    user_id=student.id).count()
    assert filas == 1
    assert segundo.answers == {"situacion_laboral": "empleado"}


def test_get_draft_devuelve_lo_guardado_y_none_para_otro_usuario(
    db_session, make_survey_form, make_student,
):
    form = make_survey_form(code="tt_test_getdraft")
    mio = make_student()
    ajeno = make_student()
    SurveyService.save_draft(db_session, form.id, mio.id, {"situacion_laboral": "empleado"})

    assert SurveyService.get_draft(db_session, form.id, mio.id).answers == {
        "situacion_laboral": "empleado"}
    assert SurveyService.get_draft(db_session, form.id, ajeno.id) is None


def test_save_draft_RECHAZA_por_encima_del_tope_en_vez_de_truncar(
    db_session, make_survey_form, make_student,
):
    """Seccion 8.2: se acota la longitud serializada RECHAZANDO, no truncando."""
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(code="tt_test_tope")
    student = make_student()
    enorme = {"comentario": "x" * (MAX_ANSWERS_JSON_BYTES + 1024)}

    with pytest.raises(ValueError):
        SurveyService.save_draft(db_session, form.id, student.id, enorme)

    assert db_session.query(SurveyDraft).filter_by(form_id=form.id,
                                                   user_id=student.id).count() == 0
