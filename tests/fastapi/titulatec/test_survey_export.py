"""Export CSV: escapado de inyeccion de formulas (seccion 8.2).

Es la primera vez que el repo exporta contenido de autor NO confiable, y el
destinatario lo abre en Excel en una maquina con acceso admin a titulatec.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.services.survey_service import SurveyService, escape_formula

SCHEMA_LIBRE = {
    "enabled": True,
    "fields": [{"key": "comentario", "type": "textarea", "label": "Comentarios",
                "validation": {"maxLength": 500}}],
}


@pytest.mark.parametrize("crudo", ["=1+1", "+34", "-5", "@SUM(A1)", "\tx", "\rx"])
def test_escape_formula_prefija_los_seis_lideres(crudo):
    assert escape_formula(crudo) == "'" + crudo


@pytest.mark.parametrize("crudo", ["Todo bien", "", "1900", "a=b"])
def test_escape_formula_no_toca_lo_demas(crudo):
    assert escape_formula(crudo) == crudo


def test_una_respuesta_que_empieza_con_igual_sale_prefijada(db_session, make_survey_form):
    form = make_survey_form(code="tt_test_csv", schema=SCHEMA_LIBRE)
    SurveyService.submit(
        db_session, form,
        {"comentario": '=HYPERLINK("http://malo","clic")'},
        user_id=None, client_ip=None, user_agent=None)

    headers, rows = SurveyService.export_rows(db_session, form.id)

    assert "comentario" in headers
    columna = headers.index("comentario")
    assert len(rows) == 1
    assert rows[0][columna].startswith("'=HYPERLINK")


def test_el_escapado_alcanza_a_las_columnas_FIJAS_no_solo_a_las_respuestas(
    db_session, make_survey_form, make_student,
):
    """Seccion 8.2: el escapado es incondicional y para TODA columna.

    `numero_control` se copia del usuario, y ese valor entra por el importador de
    CSV, que —a diferencia de `core/api/users_admin.py`— NO lo valida. Basta un
    renglon torcido en el CSV de una generacion para que la columna nazca con un
    `=` al frente, y esa celda viaja al mismo Excel que abre Servicios Escolares.
    Escapar solo las respuestas deja fuera precisamente las columnas que nadie
    revisa porque "las escribe el sistema".
    """
    form = make_survey_form(code="tt_test_csv_fijas", schema=SCHEMA_LIBRE)
    student = make_student(control_number='=1+1')
    SurveyService.submit(db_session, form, {"comentario": "Todo bien"},
                         user_id=student.id, client_ip=None, user_agent=None)

    headers, rows = SurveyService.export_rows(db_session, form.id)

    columna = headers.index("numero_control")
    assert rows[0][columna] == "'=1+1"


def test_el_export_de_un_formulario_sin_respuestas_trae_encabezados_y_cero_filas(
    db_session, make_survey_form,
):
    form = make_survey_form(code="tt_test_csv_vacio", schema=SCHEMA_LIBRE)

    headers, rows = SurveyService.export_rows(db_session, form.id)

    assert headers and headers[0] == "id"
    assert rows == []
