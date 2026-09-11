"""Exportación CSV de las respuestas, a nivel HTTP.

El escapado en sí lo prueba `test_survey_export.py` (Tarea 10) contra
`escape_formula` y `SurveyService.export_rows`. Aquí se prueba que la RUTA no lo
deshace: que el CSV que sale por el cable trae el apóstrofo, el BOM y el
`Content-Disposition`, y que el permiso de exportar es distinto del de la página.

Es la primera vez que el repo exporta contenido de autor NO CONFIABLE: lo
escribe un anónimo y el destinatario lo abre en Excel en una máquina con acceso
admin a titulatec. Toda celda que empiece con `=`, `+`, `-`, `@`, TAB o CR sale
prefijada con un apóstrofo (§8.2).
"""
from __future__ import annotations

import uuid

URL = "/titulatec/admin/encuestas/export.csv"

EXPORT_PERMS = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.export",
    "titulatec.process.api.read.all",
)


def _form_con_respuesta(db_session, texto):
    """Formulario con código único: el índice parcial `uq_titulatec_survey_forms_open`
    solo deja UNA versión abierta por `code`, y la BD de dev puede traer ya la real."""
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyForm, SurveyResponse

    form = SurveyForm(
        code=f"egresados_test_{uuid.uuid4().hex[:8]}",
        title="Encuesta de egresados (prueba)",
        schema={"enabled": True, "fields": [
            {"key": "comentarios", "type": "textarea", "label": "Comentarios",
             "required": False, "validation": {"maxLength": 500}}]},
        version=1, status="open", is_anonymous=False,
    )
    db_session.add(form)
    db_session.flush()

    resp = SurveyResponse(form_id=form.id, form_version=1,
                          identity_source="anonymous", answers={"comentarios": texto})
    db_session.add(resp)
    db_session.flush()
    db_session.add(SurveyAnswer(response_id=resp.id, field_key="comentarios",
                                field_type="textarea", value_text=texto))
    db_session.flush()
    return form


def test_una_respuesta_que_empieza_con_igual_sale_prefijada_con_apostrofo(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=EXPORT_PERMS)
    form = _form_con_respuesta(db_session, "=1+1")

    resp = client_as(head).get(f"{URL}?form_id={form.id}")

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    cuerpo = resp.content.decode("utf-8")
    assert "'=1+1" in cuerpo
    # La celda cruda NO puede aparecer sin el apóstrofo delante.
    assert ",=1+1" not in cuerpo
    assert cuerpo.startswith("﻿")   # BOM para Excel en Windows


def test_el_csv_tambien_escapa_mas_menos_y_arroba(client_as, db_session, make_head):
    head = make_head(perm_codes=EXPORT_PERMS)
    for texto in ("+SUM(A1)", "-2+3", "@import"):
        form = _form_con_respuesta(db_session, texto)
        resp = client_as(head).get(f"{URL}?form_id={form.id}")
        assert resp.status_code == 200, resp.text[:300]
        assert "'" + texto in resp.content.decode("utf-8"), texto


def test_exportar_sin_el_permiso_de_exportacion_se_rechaza(
    client_as, db_session, make_head,
):
    """`perms=[...]` es OR: `survey.page.list` NO alcanza para exportar."""
    head = make_head(perm_codes=("titulatec.survey.page.list",))
    form = _form_con_respuesta(db_session, "sin fórmula")

    resp = client_as(head).get(f"{URL}?form_id={form.id}")

    assert resp.status_code == 403, resp.text[:300]
