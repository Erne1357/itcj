"""Rutas del reporte Excel de la encuesta (`pages/surveys_admin.py`).

El servicio lo cubre `test_survey_report_service.py`; aquí, el HTTP: permiso,
liga compartida pre-pintada, parcial, libro descargable, CSV intacto y el orden
de declaración frente a `/{response_id}`.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import pytest

BASE = "/titulatec/admin/encuestas"
PREFIX = "/admin/encuestas"
PERMS = ("titulatec.survey.page.list", "titulatec.survey.api.export")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SCHEMA = {
    "sections": [{"key": "perfil", "title": "Perfil"}],
    "fields": [
        {"key": "nombre_completo", "type": "text", "label": "Nombre completo", "section": "perfil"},
        {"key": "carrera_egreso", "type": "radio", "label": "Carrera de egreso", "section": "perfil",
         "options": [{"label": "Sistemas", "value": "Sistemas"},
                     {"label": "Industrial", "value": "Industrial"}]},
        {"key": "recibir_correos", "type": "radio", "label": "¿Recibir correos?", "section": "perfil",
         "options": [{"label": "Si", "value": "Si"}, {"label": "No", "value": "No"}]},
    ],
}


@pytest.fixture()
def form(db_session):
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyForm, SurveyResponse

    f = SurveyForm(code=f"rep_{uuid.uuid4().hex[:8]}", title="Encuesta de prueba",
                   schema=SCHEMA, version=1, status="closed", is_anonymous=False)
    db_session.add(f)
    db_session.flush()
    for nombre, carrera, correos in (("Ana", "Sistemas", "Si"), ("Beto", "Industrial", "No"),
                                     ("Cira", "Sistemas", "Si")):
        r = SurveyResponse(form_id=f.id, form_version=1, identity_source="anonymous",
                           answers={"nombre_completo": nombre, "carrera_egreso": carrera,
                                    "recibir_correos": correos},
                           submitted_at=datetime(2026, 3, 1, 10, 0))
        db_session.add(r)
    db_session.flush()
    return f


@pytest.fixture()
def head(make_head):
    return make_head(perm_codes=PERMS)


def test_las_tres_rutas_piden_el_permiso_de_exportar(client_as, make_head, form):
    solo_lista = make_head(perm_codes=("titulatec.survey.page.list",))
    c = client_as(solo_lista)
    for ruta in ("/reporte", "/reporte/vista", "/reporte.xlsx"):
        assert c.get(f"{BASE}{ruta}?form_id={form.id}").status_code == 403, ruta


def test_la_pagina_pinta_una_liga_compartida(client_as, head, form):
    q = (f"form_id={form.id}&cols=_nombre,carrera_egreso&orden=carrera_egreso:desc"
         "&f_recibir_correos=Si&unico=1&hojas=resumen")
    r = client_as(head).get(f"{BASE}/reporte?{q}")
    assert r.status_code == 200, r.text[:500]
    html = r.text
    assert 'id="tt-report-form"' in html and 'id="tt-report-preview"' in html
    assert 'name="cols" id="tt-sr-cols" value="_nombre,carrera_egreso"' in html
    assert 'id="tt-sr-col-carrera_egreso"' in html
    assert 'id="tt-sr-col-recibir_correos"' not in html          # columna no pedida
    import re
    assert re.search(r'name="f_recibir_correos" value="Si"\s+checked', html)
    assert re.search(r'name="unico" value="1"\s+checked', html)


def test_la_pagina_sin_formulario_no_revienta(client_as, head):
    assert client_as(head).get(f"{BASE}/reporte?form_id=99999999").status_code == 200


def test_el_parcial_trae_el_total(client_as, head, form):
    r = client_as(head).get(f"{BASE}/reporte/vista?form_id={form.id}&cols=nombre_completo&f_recibir_correos=Si")
    assert r.status_code == 200, r.text[:500]
    assert 'id="tt-report-preview"' in r.text
    assert "2 respuestas" in r.text
    assert "Ana" in r.text and "Beto" not in r.text


def test_el_parcial_de_un_formulario_inexistente_es_404(client_as, head):
    assert client_as(head).get(f"{BASE}/reporte/vista?form_id=99999999").status_code == 404


def test_el_xlsx_baja_con_sus_cabeceras_y_abre_con_openpyxl(client_as, head, form):
    import openpyxl

    r = client_as(head).get(f"{BASE}/reporte.xlsx?form_id={form.id}&cols=_nombre,carrera_egreso")
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith(XLSX)
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment") and f"reporte-encuesta-{form.code}-v1-" in cd and cd.endswith('.xlsx"')
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert "Respuestas" in wb.sheetnames


def test_el_xlsx_de_un_formulario_inexistente_es_404(client_as, head):
    assert client_as(head).get(f"{BASE}/reporte.xlsx?form_id=99999999").status_code == 404


def test_el_csv_crudo_sigue_igual(client_as, head, form):
    r = client_as(head).get(f"{BASE}/export.csv?form_id={form.id}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.content.decode("utf-8").startswith("﻿")


def test_la_bandeja_ofrece_ambos_botones(client_as, head, form):
    r = client_as(head).get(f"{BASE}/body?form_id={form.id}")
    assert r.status_code == 200
    assert f"{BASE}/reporte?form_id={form.id}" in r.text
    assert "CSV (datos crudos)" in r.text


def test_las_rutas_del_reporte_se_declaran_antes_que_el_detalle():
    from itcj2.apps.titulatec.pages.surveys_admin import router

    paths = [getattr(x, "path", "") for x in router.routes]
    detalle = paths.index(f"{PREFIX}/{{response_id}}")
    for ruta in ("/reporte", "/reporte/vista", "/reporte.xlsx"):
        assert paths.index(PREFIX + ruta) < detalle, ruta
