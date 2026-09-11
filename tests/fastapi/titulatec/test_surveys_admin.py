"""Bandeja de respuestas de la encuesta de egresados.

`/encuestas` y `/encuestas/body` aceptan LOS MISMOS query params: la ruta
hermana devuelve el parcial, nunca se olfatea `HX-Request`.
"""
from __future__ import annotations

import uuid

URL = "/titulatec/admin/encuestas"

SURVEY_PERMS = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.process.api.read.all",
)


def _make_form(db_session, *, status="open"):
    """Formulario con código único: el índice parcial solo deja UNA versión
    abierta por `code`, y la BD de dev puede traer ya la real."""
    from itcj2.apps.titulatec.models import SurveyForm

    form = SurveyForm(
        code=f"egresados_test_{uuid.uuid4().hex[:8]}",
        title="Encuesta de egresados (prueba)",
        description=None,
        schema={"enabled": True, "fields": [
            {"key": "situacion_laboral", "type": "radio",
             "label": "¿Cuál es tu situación laboral actual?", "required": True,
             "options": [{"value": "empleado", "label": "Trabajando"},
                         {"value": "buscando", "label": "Buscando empleo"}]},
            {"key": "comentarios", "type": "textarea", "label": "Comentarios",
             "required": False, "validation": {"maxLength": 500}},
        ]},
        version=1, status=status, is_anonymous=False,
    )
    db_session.add(form)
    db_session.flush()
    return form


def _make_response(db_session, form, *, answers, user=None, control=None):
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyResponse

    resp = SurveyResponse(
        form_id=form.id, form_version=form.version,
        user_id=getattr(user, "id", None),
        identity_source="session" if user is not None else "anonymous",
        control_number=control,
        answers=answers,
    )
    db_session.add(resp)
    db_session.flush()
    for key, val in answers.items():
        db_session.add(SurveyAnswer(response_id=resp.id, field_key=key,
                                    field_type="textarea", value_text=str(val)))
    db_session.flush()
    return resp


def test_la_bandeja_lista_las_respuestas_del_formulario(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    _make_response(db_session, form, answers={"situacion_laboral": "empleado"},
                   control="99440001")

    resp = client_as(head).get(f"{URL}?form_id={form.id}")

    assert resp.status_code == 200, resp.text[:500]
    assert "99440001" in resp.text
    # El título del formulario se imprime tal cual: el `<option>` del selector
    # solo trae `code v{n} (status)`, así que sin esa línea la bandeja nunca dice
    # QUÉ cuestionario se está viendo.
    assert form.title in resp.text


def test_body_acepta_los_mismos_query_params_que_la_pagina(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    _make_response(db_session, form, answers={"situacion_laboral": "empleado"},
                   control="99440002")
    c = client_as(head)

    pagina = c.get(f"{URL}?form_id={form.id}")
    body = c.get(f"{URL}/body?form_id={form.id}")

    assert pagina.status_code == 200 and body.status_code == 200
    assert 'id="tt-surveys-body"' in body.text
    assert "99440002" in body.text


def test_el_detalle_muestra_las_respuestas_de_una_fila(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    r = _make_response(db_session, form,
                       answers={"comentarios": "Me faltó orientación laboral"},
                       control="99440003")

    resp = client_as(head).get(f"{URL}/{r.id}")

    assert resp.status_code == 200, resp.text[:500]
    assert "Me faltó orientación laboral" in resp.text


def test_sin_el_permiso_de_la_pagina_no_se_abre(
    client_as, make_app_user_without_perms,
):
    resp = client_as(make_app_user_without_perms()).get(URL)

    assert resp.status_code == 403, resp.text[:300]
