"""Escritura de una respuesta: seccion 4.4 del diseno.

Cubre el mapeo tipo -> columna, el congelado de `form_version`, que `answers`
guarde la proyeccion VALIDADA (no el cuerpo crudo) y que un envio invalido no
escriba nada.
"""
from __future__ import annotations

from itcj2.apps.titulatec.services.survey_service import (
    MAX_ANSWERS_JSON_BYTES,
    SurveyService,
    form_to_dict,
)

# Un campo de CADA tipo con fila propia, mas el multiselect que escribe N.
SCHEMA_TIPOS = {
    "enabled": True,
    "fields": [
        {"key": "comentario", "type": "textarea", "label": "Comentarios",
         "validation": {"maxLength": 500}},
        {"key": "satisfaccion", "type": "scale", "label": "Satisfaccion",
         "scale": {"min": 1, "max": 5}},
        {"key": "recomendarias", "type": "yesno", "label": "Recomendarias el Tec?"},
        {"key": "aviso", "type": "checkbox", "label": "Acepto el aviso de privacidad"},
        {"key": "idiomas", "type": "multiselect", "label": "Idiomas que dominas",
         "options": [{"value": "en", "label": "Ingles"},
                     {"value": "fr", "label": "Frances"},
                     {"value": "de", "label": "Aleman"}]},
    ],
}

ENVIO = {
    "comentario": "Todo bien",
    "satisfaccion": "4",
    "recomendarias": "true",
    "aviso": True,
    "idiomas": ["en", "fr"],
    "sueldo_declarado": "999999",      # llave desconocida: se descarta
}


def _answers(db, response):
    from itcj2.apps.titulatec.models import SurveyAnswer
    return (db.query(SurveyAnswer).filter_by(response_id=response.id)
            .order_by(SurveyAnswer.id).all())


def test_un_envio_anonimo_no_guarda_user_id(db_session, make_survey_form):
    form = make_survey_form(code="tt_test_anon", schema=SCHEMA_TIPOS)

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO, user_id=None,
        client_ip="10.0.0.9", user_agent="pytest")

    assert errors == {}
    assert credit == "anonymous"
    assert response.user_id is None
    assert response.identity_source == "anonymous"
    assert response.control_number is None
    # La IP nunca se guarda en claro.
    assert response.client_ip_hash and "10.0.0.9" not in response.client_ip_hash


def test_con_sesion_guarda_user_id_e_identity_source_session(
    db_session, make_survey_form, make_student,
):
    form = make_survey_form(code="tt_test_ses", schema=SCHEMA_TIPOS)
    student = make_student(control_number="99000777")

    response, errors, _credit = SurveyService.submit(
        db_session, form, ENVIO, user_id=student.id, client_ip=None, user_agent=None)

    assert errors == {}
    assert response.user_id == student.id
    assert response.identity_source == "session"
    # El control se COPIA del usuario en sesion, nunca se auto-declara (D1).
    assert response.control_number == "99000777"


def test_una_fila_por_campo_salvo_multiselect_que_escribe_N(
    db_session, make_survey_form,
):
    form = make_survey_form(code="tt_test_filas", schema=SCHEMA_TIPOS)

    response, _errors, _credit = SurveyService.submit(
        db_session, form, ENVIO, user_id=None, client_ip=None, user_agent=None)

    filas = _answers(db_session, response)
    por_llave = {}
    for fila in filas:
        por_llave.setdefault(fila.field_key, []).append(fila)

    assert len(filas) == 6, [(f.field_key, f.field_type) for f in filas]
    assert len(por_llave["comentario"]) == 1
    assert len(por_llave["satisfaccion"]) == 1
    assert len(por_llave["recomendarias"]) == 1
    assert len(por_llave["aviso"]) == 1
    assert len(por_llave["idiomas"]) == 2          # una fila por opcion marcada

    assert por_llave["comentario"][0].value_text == "Todo bien"
    assert int(por_llave["satisfaccion"][0].value_num) == 4
    assert por_llave["recomendarias"][0].value_bool is True
    assert por_llave["aviso"][0].value_bool is True
    # Las dos del multiselect son DISTINGUIBLES: valor en `value_text`, marca en bool.
    assert {f.value_text for f in por_llave["idiomas"]} == {"en", "fr"}
    assert all(f.value_bool is True for f in por_llave["idiomas"])
    assert all(f.field_type == "multiselect" for f in por_llave["idiomas"])


def test_form_version_queda_congelada_y_answers_guarda_cleaned(
    db_session, make_survey_form,
):
    """Snapshot: una v2 posterior no puede reinterpretar esta respuesta."""
    form = make_survey_form(code="tt_test_ver", version=7, schema=SCHEMA_TIPOS)

    response, _errors, _credit = SurveyService.submit(
        db_session, form, ENVIO, user_id=None, client_ip=None, user_agent=None)

    assert response.form_version == 7
    assert response.answers == {
        "comentario": "Todo bien",
        "satisfaccion": 4,
        "recomendarias": True,
        "aviso": True,
        "idiomas": ["en", "fr"],
    }
    assert "sueldo_declarado" not in response.answers


def test_un_envio_invalido_no_escribe_NADA(db_session, make_survey_form):
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyResponse

    form = make_survey_form(code="tt_test_invalido")   # schema v1: radio obligatorio
    antes_r = db_session.query(SurveyResponse).count()
    antes_a = db_session.query(SurveyAnswer).count()

    response, errors, credit = SurveyService.submit(
        db_session, form, {}, user_id=None, client_ip=None, user_agent=None)

    assert response is None
    assert "situacion_laboral" in errors
    assert credit == "anonymous"
    assert db_session.query(SurveyResponse).count() == antes_r
    assert db_session.query(SurveyAnswer).count() == antes_a


def test_una_respuesta_por_encima_del_tope_se_RECHAZA(db_session, make_survey_form):
    """Seccion 8.2: se rechaza, no se trunca."""
    from itcj2.apps.titulatec.models import SurveyResponse

    schema = {"enabled": True,
              "fields": [{"key": "comentario", "type": "textarea", "label": "Comentarios",
                          "validation": {"maxLength": MAX_ANSWERS_JSON_BYTES * 2}}]}
    form = make_survey_form(code="tt_test_gordo", schema=schema)
    antes = db_session.query(SurveyResponse).count()

    response, errors, _credit = SurveyService.submit(
        db_session, form, {"comentario": "x" * (MAX_ANSWERS_JSON_BYTES + 1024)},
        user_id=None, client_ip=None, user_agent=None)

    assert response is None
    assert errors                                   # hay mensaje para la pagina
    assert db_session.query(SurveyResponse).count() == antes


def test_enviar_borra_el_borrador_del_alumno(db_session, make_survey_form, make_student):
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(code="tt_test_limpia", schema=SCHEMA_TIPOS)
    student = make_student()
    SurveyService.save_draft(db_session, form.id, student.id, {"comentario": "a medias"})

    SurveyService.submit(db_session, form, ENVIO, user_id=student.id,
                         client_ip=None, user_agent=None)

    assert db_session.query(SurveyDraft).filter_by(
        form_id=form.id, user_id=student.id).count() == 0


def test_enviar_NO_toca_el_borrador_de_los_demas(db_session, make_survey_form,
                                                 make_student):
    """El borrado va acotado por `user_id`, no solo por `form_id`.

    Sin esa mitad del filtro, el primer alumno que envia le borra el borrador a
    TODOS los demas que estan a medio contestar el mismo formulario — en una
    encuesta que se promueve a una generacion entera, eso es la mayoria. Es
    ademas silencioso: el afectado solo lo descubre al volver y encontrar la
    pagina en blanco.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(code="tt_test_ajeno", schema=SCHEMA_TIPOS)
    quien_envia = make_student()
    quien_sigue_escribiendo = make_student()
    SurveyService.save_draft(db_session, form.id, quien_envia.id, {"comentario": "mio"})
    SurveyService.save_draft(db_session, form.id, quien_sigue_escribiendo.id,
                             {"comentario": "a medias, no me lo borres"})

    SurveyService.submit(db_session, form, ENVIO, user_id=quien_envia.id,
                         client_ip=None, user_agent=None)

    ajeno = SurveyService.get_draft(db_session, form.id, quien_sigue_escribiendo.id)
    assert ajeno is not None
    assert ajeno.answers == {"comentario": "a medias, no me lo borres"}


# ---------------------------------------------------------------------------
# El puente entre `await request.form()` y `submit` (lo consume la Tarea 12)
# ---------------------------------------------------------------------------
def test_form_to_dict_recupera_TODAS_las_opciones_de_un_multiselect():
    """`FormData.get()` devuelve SOLO LA ULTIMA de las llaves repetidas.

    Un grupo de casillas manda la llave N veces —`[("idiomas","en"),
    ("idiomas","fr")]`— y `FormData` NO la colapsa a lista: `.get("idiomas")`
    devuelve `'fr'`, y `dict(form_data)` lo mismo. Pasar ese dict a
    `validate_answers` hace que TODO multiselect falle con "se esperaba una
    lista de opciones" (o, si es obligatorio, "selecciona al menos una
    opcion"). Falla cerrado, asi que no es un agujero — pero rompe la funcion
    en silencio y culpando al campo equivocado.

    Por eso el puente vive AQUI y no en la pagina: quien sabe que llaves son
    `multiselect` es el `schema`, y este modulo ya lo interpreta.
    """
    from starlette.datastructures import FormData

    crudo = FormData([("idiomas", "en"), ("idiomas", "fr"),
                      ("comentario", "Todo bien"), ("satisfaccion", "4")])

    assert crudo.get("idiomas") == "fr"          # el comportamiento que sorprende
    submitted = form_to_dict(SCHEMA_TIPOS, crudo)

    assert submitted["idiomas"] == ["en", "fr"]
    assert submitted["comentario"] == "Todo bien"
    assert submitted["satisfaccion"] == "4"


def test_form_to_dict_deja_lista_VACIA_cuando_no_se_marco_ninguna_casilla():
    """Ausente -> `[]`, que es "no contestado" para un opcional y error para un
    obligatorio. Las dos ramas las decide el validador, no este puente."""
    from starlette.datastructures import FormData

    submitted = form_to_dict(SCHEMA_TIPOS, FormData([("comentario", "hola")]))

    assert submitted["idiomas"] == []


def test_un_envio_que_viene_de_un_FormData_real_se_guarda_completo(
    db_session, make_survey_form,
):
    """La prueba de punta a punta del puente: `FormData` -> `form_to_dict` ->
    `submit` escribe las DOS filas del multiselect, no una."""
    from starlette.datastructures import FormData

    form = make_survey_form(code="tt_test_formdata", schema=SCHEMA_TIPOS)
    crudo = FormData([("comentario", "Todo bien"), ("satisfaccion", "4"),
                      ("recomendarias", "true"), ("aviso", "on"),
                      ("idiomas", "en"), ("idiomas", "fr")])

    response, errors, _credit = SurveyService.submit(
        db_session, form, form_to_dict(SCHEMA_TIPOS, crudo),
        user_id=None, client_ip=None, user_agent=None)

    assert errors == {}
    assert response.answers["idiomas"] == ["en", "fr"]
    idiomas = [f for f in _answers(db_session, response) if f.field_key == "idiomas"]
    assert len(idiomas) == 2
