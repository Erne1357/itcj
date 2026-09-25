"""Bandeja de respuestas de la encuesta de egresados.

`/encuestas` y `/encuestas/body` aceptan LOS MISMOS query params: la ruta
hermana devuelve el parcial, nunca se olfatea `HX-Request`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

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


def _make_response(db_session, form, *, answers, user=None, control=None,
                   submitted_at=None):
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyResponse

    resp = SurveyResponse(
        form_id=form.id, form_version=form.version,
        user_id=getattr(user, "id", None),
        identity_source="session" if user is not None else "anonymous",
        control_number=control,
        answers=answers,
    )
    if submitted_at is not None:
        # Asignado DESPUÉS de construir el objeto: si se pasara `None` al
        # constructor, SQLAlchemy lo tomaría como un valor explícito y el
        # INSERT mandaría NULL en vez de dejar que el `server_default` ponga
        # NOW() (la columna es NOT NULL).
        resp.submitted_at = submitted_at
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


def test_una_respuesta_totalmente_anonima_se_ve_en_lista_y_detalle(
    client_as, db_session, make_head,
):
    """La encuesta se promueve en público y no exige sesión: un anónimo puro
    (sin usuario, sin proceso, sin convocatoria, sin número de control) es el
    caso MÁS común en producción, no el raro — al revés de lo que cubrían los
    demás tests de este archivo, que siempre traen `control_number`.

    Ninguna columna de identidad puede tumbar la plantilla: si alguien
    simplifica `u.full_name if u else "Anónimo"` a `u.full_name`, o quita la
    guarda `if row.user_id` antes de buscar al usuario, esta fila hace que la
    lista y el detalle truenen en vez de mostrar "Anónimo".
    """
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    r = _make_response(db_session, form, answers={"comentarios": "Nada que reportar"})
    # Verifica que la fixture de verdad produce las CUATRO columnas en NULL,
    # no solo `control_number` (que ya cubrían los demás tests).
    assert r.user_id is None
    assert r.process_id is None
    assert r.cohort_id is None
    assert r.control_number is None

    lista = client_as(head).get(f"{URL}?form_id={form.id}")
    detalle = client_as(head).get(f"{URL}/{r.id}")

    assert lista.status_code == 200, lista.text[:500]
    assert "Anónimo" in lista.text
    assert detalle.status_code == 200, detalle.text[:500]
    assert "Anónimo" in detalle.text


def test_sin_el_permiso_de_la_pagina_no_se_abre(
    client_as, make_app_user_without_perms,
):
    resp = client_as(make_app_user_without_perms()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_ver_el_detalle_sin_el_permiso_de_lectura_se_rechaza(
    client_as, db_session, make_head,
):
    """`perms=[...]` es OR, pero la ruta de detalle trae un SOLO código
    (`survey.api.read`, distinto de `survey.page.list`): quien solo puede ver
    la bandeja NO puede abrir una fila individual. Espejo de
    `test_exportar_sin_el_permiso_de_exportacion_se_rechaza`
    (`test_survey_export_route.py`), mismo principio para el otro código
    exclusivo de este módulo.
    """
    head = make_head(perm_codes=("titulatec.survey.page.list",))
    form = _make_form(db_session)
    r = _make_response(db_session, form, answers={"comentarios": "x"},
                       control="99440004")

    resp = client_as(head).get(f"{URL}/{r.id}")

    assert resp.status_code == 403, resp.text[:300]


# ---------------------------------------------------------------------------
# FIFO (2026-09-24): la bandeja se recorre en el orden en que llegaron
# ---------------------------------------------------------------------------
# En las pruebas de abajo el id de inserción va al REVÉS de `submitted_at`, a
# propósito: si la ruta ordenara por `id` o por `submitted_at` descendente (el
# comportamiento de antes), estas pruebas fallarían.
def test_las_respuestas_se_ordenan_de_la_mas_antigua_a_la_mas_nueva(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    mas_nueva = _make_response(db_session, form, answers={"comentarios": "reciente"},
                               control="99620001",
                               submitted_at=datetime(2001, 1, 2, 9, 0))
    mas_antigua = _make_response(db_session, form, answers={"comentarios": "vieja"},
                                 control="99620002",
                                 submitted_at=datetime(2001, 1, 1, 9, 0))
    assert mas_antigua.id > mas_nueva.id, "el id debe ir al revés de submitted_at"

    html = client_as(head).get(f"{URL}/body?form_id={form.id}").text

    pos_antigua = html.index(mas_antigua.control_number)
    pos_nueva = html.index(mas_nueva.control_number)
    assert pos_antigua < pos_nueva, (
        "la bandeja debe listar de la respuesta más antigua a la más nueva")


def test_la_pagina_2_continua_a_la_1_en_el_mismo_orden_ascendente(
    client_as, db_session, make_head, monkeypatch,
):
    """Pagina con `_PAGE_SIZE` chico a propósito: 3 respuestas y 2 por página
    dejan la 3a en la página 2, y sigue en el mismo orden que la 1."""
    import itcj2.apps.titulatec.pages.surveys_admin as surveys_admin
    monkeypatch.setattr(surveys_admin, "_PAGE_SIZE", 2)

    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    mas_nueva = _make_response(db_session, form, answers={"comentarios": "c"},
                               control="99620011",
                               submitted_at=datetime(2001, 1, 3, 9, 0))
    media = _make_response(db_session, form, answers={"comentarios": "c"},
                           control="99620012",
                           submitted_at=datetime(2001, 1, 2, 9, 0))
    mas_antigua = _make_response(db_session, form, answers={"comentarios": "c"},
                                 control="99620013",
                                 submitted_at=datetime(2001, 1, 1, 9, 0))
    c = client_as(head)

    pagina1 = c.get(f"{URL}/body?form_id={form.id}&page=1")
    pagina2 = c.get(f"{URL}/body?form_id={form.id}&page=2")

    assert pagina1.status_code == 200, pagina1.text[:500]
    assert pagina2.status_code == 200, pagina2.text[:500]
    # Página 1: las DOS más viejas, en orden ascendente.
    assert mas_antigua.control_number in pagina1.text
    assert media.control_number in pagina1.text
    assert mas_nueva.control_number not in pagina1.text
    assert (pagina1.text.index(mas_antigua.control_number)
            < pagina1.text.index(media.control_number))
    assert "Siguientes" in pagina1.text
    # Página 2: sigue con la más nueva, ella sola.
    assert mas_nueva.control_number in pagina2.text
    assert mas_antigua.control_number not in pagina2.text
    assert media.control_number not in pagina2.text
    assert "Anteriores" in pagina2.text
