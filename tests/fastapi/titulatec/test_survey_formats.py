"""Encuesta de egresados: validaciones por FORMATO en la pagina (2026-09-15).

`test_survey_validator.py` fija el motor: cada formato con sus bordes, el tipo
`date`, la regla cruzada `gte_field` y `validate_schema`. Este archivo fija lo
que el visitante ve y lo que el servidor hace con ello:

  * un formato roto NO avanza el paso y se pinta en linea bajo su pregunta, con
    lo escrito de vuelta en el control, en el paso y en el envio final;
  * la regla cruzada tambien corre al validar el paso (los dos anos viven en la
    misma seccion);
  * cada formato pinta su teclado (`inputmode`, `type=tel/email/date`), su largo
    y su autollenado, y la fecha trae el `min`/`max` que calcula el servidor;
  * el formulario declara `novalidate`: el error lo pinta el servidor, no una
    burbuja del navegador;
  * un borrador con la fecha vieja `d/M/aaaa` vuelve en ISO.

Todas con sesion (`client_as(make_student())`) y con esquemas propios: la CI
corre con base vacia, sin el DML del instrumento real.
"""
from __future__ import annotations

import re

SURVEY_URL = "/titulatec/encuesta-egresados"
STEP_URL = f"{SURVEY_URL}/paso"


# ---------------------------------------------------------------------------
# Servidor: el paso no avanza con un formato roto
# ---------------------------------------------------------------------------
SCHEMA_FORMATOS = {
    "enabled": True,
    "sections": [{"key": "perfil", "title": "Perfil del egresado"},
                 {"key": "cierre", "title": "Comentarios"}],
    "fields": [
        {"key": "no_control", "section": "perfil", "type": "text", "label": "No. Control:",
         "required": True, "validation": {"format": "digits", "length": 8, "maxLength": 8}},
        {"key": "anio_ingreso", "section": "perfil", "type": "text",
         "label": "Año de INGRESO (EJ. 1999)", "required": True,
         "validation": {"format": "year", "min": 1950, "max": "current", "maxLength": 4}},
        {"key": "anio_egreso", "section": "perfil", "type": "text",
         "label": "Año de EGRESO (EJ. 1999)", "required": True,
         "validation": {"format": "year", "min": 1950, "max": "current", "maxLength": 4,
                        "gte_field": "anio_ingreso"}},
        {"key": "comentario", "section": "cierre", "type": "textarea", "label": "Comentario",
         "required": False, "validation": {"maxLength": 200}},
    ],
}


def _avanzar_desde_perfil(c, **campos):
    datos = {"tt_step": "0", "tt_next": "1", "no_control": "90200001",
             "anio_ingreso": "2015", "anio_egreso": "2020"}
    datos.update(campos)
    resp = c.post(STEP_URL, data=datos, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:400]
    return resp.text


def test_un_numero_de_control_de_siete_digitos_no_avanza_el_paso_y_pinta_el_error(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_FORMATOS)

    cuerpo = _avanzar_desde_perfil(client_as(make_student()), no_control="9020001")

    assert 'data-tt-section="perfil"' in cuerpo                 # no avanzo
    assert 'data-tt-section="cierre"' not in cuerpo
    error = re.search(r'<div class="tt-err" id="f-no_control-err" data-tt-error="no_control"'
                      r'[^>]*>(.*?)</div>', cuerpo, flags=re.S)
    assert error, "el error no se pinto en linea bajo su pregunta"
    assert "No. Control debe tener exactamente 8 dígitos" in error.group(1)
    control = re.search(r'<input\b[^>]*\bname="no_control"[^>]*>', cuerpo).group(0)
    assert 'aria-invalid="true"' in control
    assert 'value="9020001"' in control      # lo escrito vuelve, para corregirlo ahi mismo


def test_un_numero_de_control_de_ocho_digitos_avanza_al_siguiente_paso(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_FORMATOS)

    cuerpo = _avanzar_desde_perfil(client_as(make_student()), no_control="90200001")

    assert 'data-tt-section="cierre"' in cuerpo
    assert "data-tt-errors" not in cuerpo
    assert '<input type="hidden" name="no_control" value="90200001">' in cuerpo


def test_un_egreso_anterior_al_ingreso_no_avanza_el_paso(
    client_as, make_student, make_survey_form,
):
    """La regla cruzada tambien corre en el paso: los dos anos viven en el perfil."""
    make_survey_form(schema=SCHEMA_FORMATOS)

    cuerpo = _avanzar_desde_perfil(client_as(make_student()),
                                   anio_ingreso="2020", anio_egreso="2015")

    assert 'data-tt-section="perfil"' in cuerpo
    assert 'data-tt-error="anio_egreso"' in cuerpo
    assert 'data-tt-error="anio_ingreso"' not in cuerpo
    assert "Año de EGRESO no puede ser anterior a Año de INGRESO (2020)" in cuerpo


def test_el_envio_final_tambien_rechaza_un_formato_roto(
    client_as, make_student, make_survey_form, db_session,
):
    from itcj2.apps.titulatec.models import SurveyResponse

    form = make_survey_form(schema=SCHEMA_FORMATOS)

    resp = client_as(make_student()).post(
        SURVEY_URL, data={"website": "", "no_control": "9020001",
                          "anio_ingreso": "2015", "anio_egreso": "2020"},
        headers={"X-Real-IP": "203.0.113.91"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert db_session.query(SurveyResponse).filter_by(form_id=form.id).count() == 0
    assert 'data-tt-error="no_control"' in resp.text


# ---------------------------------------------------------------------------
# Cliente: el control ayuda, el servidor decide
# ---------------------------------------------------------------------------
SCHEMA_FORMATOS_UI = {
    "enabled": True,
    "sections": [{"key": "perfil", "title": "Perfil del egresado"},
                 {"key": "cierre", "title": "Comentarios finales"}],
    "fields": [
        {"key": "nombre_completo", "section": "perfil", "type": "text",
         "label": "Nombre completo", "required": True,
         "validation": {"format": "person_name", "maxLength": 200}},
        {"key": "no_control", "section": "perfil", "type": "text", "label": "No. Control:",
         "required": True, "validation": {"format": "digits", "length": 8, "maxLength": 8}},
        {"key": "fecha_nacimiento", "section": "perfil", "type": "date",
         "label": "Fecha de nacimiento", "required": True,
         "validation": {"minAge": 15, "maxAge": 90}},
        {"key": "correo_personal", "section": "perfil", "type": "text",
         "label": "Correo Personal:", "required": True,
         "validation": {"format": "email", "maxLength": 150}},
        {"key": "telefono", "section": "perfil", "type": "text",
         "label": "Número telefónico (10 dígitos):", "required": True,
         "validation": {"format": "phone", "maxLength": 20}},
        {"key": "anio_ingreso", "section": "perfil", "type": "text", "label": "Año de INGRESO",
         "required": True,
         "validation": {"format": "year", "min": 1950, "max": "current", "maxLength": 4}},
        {"key": "promedio_final", "section": "perfil", "type": "text", "label": "Promedio final",
         "required": True,
         "validation": {"format": "decimal", "min": 70, "max": 100, "maxLength": 6}},
        {"key": "telefono_rh", "section": "perfil", "type": "text",
         "label": "Teléfono del encargado de RH", "required": False, "autocomplete": "off",
         "validation": {"format": "phone", "maxLength": 20}},
        {"key": "empresa", "section": "perfil", "type": "text", "label": "Empresa",
         "required": False, "validation": {"maxLength": 80}},
        {"key": "comentario", "section": "cierre", "type": "textarea",
         "label": "Comentario final", "required": False, "validation": {"maxLength": 200}},
    ],
}


def _input(cuerpo: str, name: str) -> str:
    m = re.search(r'<input\b[^>]*\bname="%s"[^>]*>' % name, cuerpo, flags=re.S)
    assert m, f"no hay <input name={name}>"
    return " ".join(m.group(0).split())


def test_cada_formato_pinta_su_teclado_su_largo_y_su_autocompletado(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_FORMATOS_UI)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    control = _input(cuerpo, "no_control")
    for attr in ('type="text"', 'inputmode="numeric"', 'maxlength="8"', 'autocomplete="off"'):
        assert attr in control, (attr, control)
    tel = _input(cuerpo, "telefono")
    for attr in ('type="tel"', 'autocomplete="tel-national"', 'maxlength="20"'):
        assert attr in tel, (attr, tel)
    # El telefono de OTRA persona no se autollena con el del egresado.
    assert 'autocomplete="off"' in _input(cuerpo, "telefono_rh")
    correo = _input(cuerpo, "correo_personal")
    for attr in ('type="email"', 'autocomplete="email"', 'maxlength="150"'):
        assert attr in correo, (attr, correo)
    anio = _input(cuerpo, "anio_ingreso")
    for attr in ('inputmode="numeric"', 'maxlength="4"'):
        assert attr in anio, (attr, anio)
    assert 'inputmode="decimal"' in _input(cuerpo, "promedio_final")
    nombre = _input(cuerpo, "nombre_completo")
    assert 'type="text"' in nombre and 'autocomplete="name"' in nombre
    # Sin formato no se inventa nada.
    libre = _input(cuerpo, "empresa")
    assert "inputmode" not in libre and "autocomplete" not in libre


def test_la_fecha_es_un_input_date_con_el_rango_de_edad_calculado_en_el_servidor(
    client_as, make_student, make_survey_form, monkeypatch,
):
    from datetime import date

    monkeypatch.setattr("itcj2.apps.titulatec.utils.survey_validator._hoy",
                        lambda: date(2026, 9, 15))
    make_survey_form(schema=SCHEMA_FORMATOS_UI)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    fecha = _input(cuerpo, "fecha_nacimiento")
    for attr in ('type="date"', 'min="1935-09-16"', 'max="2011-09-15"', 'autocomplete="bday"'):
        assert attr in fecha, (attr, fecha)
    assert "maxlength" not in fecha


def test_el_formulario_no_delega_la_validacion_en_las_burbujas_del_navegador(
    client_as, make_student, make_survey_form,
):
    """`type="email"` y un `type="date"` con min/max activan la validacion NATIVA.

    «Enviar respuestas» es un submit nativo: sin `novalidate`, el navegador lo
    detendria con su burbuja ANTES de que htmx lo mande, y el visitante veria un
    aviso distinto del error en linea del servidor, que es la fuente de verdad.
    """
    make_survey_form(schema=SCHEMA_FORMATOS_UI)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    etiqueta = re.search(r'<form\b[^>]*\bid="tt-survey-form"[^>]*>', cuerpo, flags=re.S).group(0)
    assert re.search(r"\bnovalidate\b", etiqueta), etiqueta


def test_un_borrador_con_la_fecha_vieja_d_m_aaaa_vuelve_en_iso(
    client_as, make_student, make_survey_form, db_session,
):
    """El rotulo viejo pedia «d/M/yyyy» y hay borradores escritos asi. Un
    `<input type="date">` descarta EN SILENCIO todo valor que no sea ISO: sin
    convertirlo, la fecha ya capturada se perderia sin aviso."""
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(schema=SCHEMA_FORMATOS_UI)
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id,
                               answers={"fecha_nacimiento": "7/3/1998"}))
    db_session.flush()

    cuerpo = client_as(student).get(SURVEY_URL, follow_redirects=False).text

    assert 'value="1998-03-07"' in _input(cuerpo, "fecha_nacimiento")
