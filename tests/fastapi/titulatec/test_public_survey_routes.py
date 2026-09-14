"""Encuesta publica de TitulaTec: lo que ve alguien SIN cookie (lado GET).

El censo de rutas guardadas y las dos pruebas de `/titulatec/inscripcion` estan
en `test_public_routes.py`, que escribe la Tarea 11; aqui solo va la encuesta.
El lado POST vive en `test_survey_submit_routes.py`.

`follow_redirects=False` en TODAS: el `TestClient` sigue redirects por omision,
asi que un 302 al login se convierte en un 200 y la prueba pasaria por la razon
equivocada. Por eso ninguna asercion se conforma con el status: siempre hay un
marcador del cuerpo (el banner o el `id` del formulario).
"""
from __future__ import annotations

import re
from urllib.parse import unquote

SURVEY_URL = "/titulatec/encuesta-egresados"
STEP_URL = f"{SURVEY_URL}/paso"     # Tarea 3: avanza/retrocede un paso

# Copia EXACTA del aviso persistente del spec 6.1: ambas frases van en el MISMO
# <p> y contiguas, asi que el corte en dos constantes es defensivo (aguanta un
# re-ajuste de la copia), no descriptivo. Los acentos son parte del literal: la
# plantilla los lleva y la E2E de la Tarea 25 los aserta.
BANNER_1 = "No iniciaste sesión."
BANNER_2 = "NO quedará en tu expediente de titulación."


def test_encuesta_anonima_devuelve_200_con_el_formulario(client, make_survey_form):
    """Sin cookie: 200 de verdad, no un 302 al login seguido por el cliente.

    Tarea 2: la apertura sin sesion ahora depende de `is_anonymous=True`
    explicito -la fabrica por omision ya es `False`, que es la realidad que
    tendra el instrumento real-. Este test SI es el camino anonimo de verdad.
    """
    make_survey_form(is_anonymous=True)
    client.cookies.clear()

    resp = client.get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-form"' in resp.text
    assert 'data-tt-page="public_survey"' in resp.text


def test_encuesta_anonima_muestra_el_banner_de_que_no_acredita(client, make_survey_form):
    """El aviso del spec 6.1 es persistente, no un toast que se va.

    Tarea 2: banner exclusivo del camino anonimo -> `is_anonymous=True` explicito.
    """
    make_survey_form(is_anonymous=True)
    client.cookies.clear()

    resp = client.get(SURVEY_URL, follow_redirects=False)

    assert BANNER_1 in resp.text
    assert BANNER_2 in resp.text
    assert "data-tt-anon-notice" in resp.text
    assert 'href="/itcj/login?next=/titulatec/encuesta-egresados"' in resp.text


def test_encuesta_con_sesion_cambia_el_banner_por_el_aviso_de_que_si_acredita(
    client_as, make_student, make_survey_form,
):
    """Con sesion no hay banner de anonimo: hay aviso de que SI acredita."""
    make_survey_form()

    resp = client_as(make_student()).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert BANNER_1 not in resp.text
    assert "data-tt-anon-notice" not in resp.text   # el gancho, no solo la copia
    assert "sí acredita" in resp.text


def test_encuesta_precarga_el_borrador_del_servidor(
    client_as, make_student, make_survey_form, db_session,
):
    """Con sesion, lo ya capturado vuelve marcado (criterio de aceptacion 5).

    Tarea 3 (ronda 2): la GET ahora reanuda con `_start_step` -el primer paso
    con un obligatorio VISIBLE sin contestar-, no siempre en el paso 0. Con
    `situacion_laboral="buscando"`, `relacion_carrera` (el otro obligatorio de
    "empleo") queda INVISIBLE -su `visible_when` pide "empleado"- y "opinion"
    no tiene ningun obligatorio, asi que `_start_step` aterrizaria en
    "opinion", donde `situacion_laboral` ya no es un control vivo. Se usa
    "empleado" en vez de "buscando": deja `relacion_carrera` visible y sin
    contestar, que es lo que mantiene a "empleo" -y por tanto al radio que
    esta prueba mide- como el paso de arranque.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form()
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id,
                               answers={"situacion_laboral": "empleado"}))
    db_session.flush()

    resp = client_as(student).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    # El `checked` tiene que estar en EL MISMO control que lleva ese `value`,
    # no en cualquier sitio de la pagina: por eso el regex y no dos `in`.
    assert re.search(r'value="empleado"[^>]*\schecked', resp.text), \
        "la opcion del borrador no vuelve marcada"


def test_el_borrador_de_otro_alumno_no_se_precarga(
    client_as, make_student, make_survey_form, db_session,
):
    """`get_draft` va por (form_id, user_id). Con solo `form_id`, el borrador de
    quien contesto primero se le pintaria a toda la generacion — y sus respuestas
    entrarian en la respuesta de otra persona sin que nadie lo note.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form()
    ajeno, propio = make_student(), make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=ajeno.id,
                               answers={"situacion_laboral": "buscando",
                                        "comentarios": "TEXTO DEL OTRO ALUMNO"}))
    db_session.flush()

    resp = client_as(propio).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert "TEXTO DEL OTRO ALUMNO" not in resp.text
    assert not re.search(r'value="buscando"[^>]*\schecked', resp.text)


def test_encuesta_sin_formulario_abierto_muestra_tarjeta_no_500(client, db_session):
    """Sin formulario publicado, el visitante ve una tarjeta, no un error.

    Esta prueba NO pasa por `make_survey_form`, que es quien cierra las versiones
    abiertas del mismo `code`. El barrido va explicito: la BD de dev puede traer
    ya la v1 sembrada por `11_seed_survey_form.sql` (Tarea 24) y entonces si hay
    formulario abierto, con lo que la asercion caeria por una razon ajena.
    """
    from itcj2.apps.titulatec.models import SurveyForm

    (db_session.query(SurveyForm)
     .filter(SurveyForm.code == "egresados", SurveyForm.status == "open")
     .update({"status": "closed"}, synchronize_session=False))
    db_session.flush()
    client.cookies.clear()

    resp = client.get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-notice="closed"' in resp.text
    assert 'id="tt-survey-form"' not in resp.text


def test_post_sin_formulario_abierto_400_con_x_tt_error_percent_codificado(
    client, db_session,
):
    """Unico 400 publico: no hay formulario que re-renderizar (spec 6.1).

    Los valores de header son latin-1 por especificacion; el mensaje va
    percent-codificado y tiene que hacer round-trip con `unquote()`.

    Mismo barrido explicito que la prueba anterior, y por el mismo motivo.
    """
    from itcj2.apps.titulatec.models import SurveyForm

    (db_session.query(SurveyForm)
     .filter(SurveyForm.code == "egresados", SurveyForm.status == "open")
     .update({"status": "closed"}, synchronize_session=False))
    db_session.flush()
    client.cookies.clear()

    resp = client.post(SURVEY_URL, data={"website": ""},
                       headers={"X-Real-IP": "203.0.113.11"},
                       follow_redirects=False)

    assert resp.status_code == 400, resp.text[:500]
    crudo = resp.headers["X-Tt-Error"]
    assert "%" in crudo, crudo
    assert unquote(crudo) == "La encuesta ya no está disponible. Recarga la página."


# ---------------------------------------------------------------------------
# Ganchos de DOM del contrato (los consumen las Tareas 13, 14, 25, 26 y 27)
# ---------------------------------------------------------------------------
def test_el_formulario_publica_los_ganchos_de_dom_del_contrato(client, make_survey_form):
    """Ninguna tarea posterior los inventa: los emite esta.

    Se miden juntos y no uno por test porque son un solo contrato: si el
    formulario deja de emitir cualquiera de ellos, lo que se rompe es la tarea
    que lo consume (el autoguardado, el E2E), no esta.

    Tarea 2: dos de estos ganchos (`data-tt-auth="0"`, `data-tt-login`) SOLO
    existen en el render anonimo -> `is_anonymous=True` explicito. No es
    comodidad: es lo que este test mide.

    Tarea 3: la carga inicial ahora es el PASO 0 -"empleo", la primera de las
    dos secciones de `SURVEY_SCHEMA_V1`-, no el formulario entero. Con dos
    secciones, ese primer paso ya no es el ultimo: el boton que ofrece es
    "Siguiente", y "Enviar respuestas" -que sigue siendo la etiqueta exacta,
    ver `test_survey_steps.py`- solo aparece en la seccion "opinion".
    """
    make_survey_form(is_anonymous=True)
    client.cookies.clear()

    cuerpo = client.get(SURVEY_URL, follow_redirects=False).text

    assert 'id="tt-survey-form"' in cuerpo
    assert 'data-tt-survey="egresados"' in cuerpo
    assert "data-tt-version=" in cuerpo
    assert 'data-tt-auth="0"' in cuerpo               # anonimo
    assert 'data-tt-draft-url="/titulatec/encuesta-egresados/borrador"' in cuerpo
    assert "data-tt-draft-updated=" in cuerpo
    assert 'data-tt-section="empleo"' in cuerpo       # una seccion por grupo
    assert 'data-tt-field="situacion_laboral"' in cuerpo
    assert "data-tt-login" in cuerpo
    # El destino del swap es la propia raiz: si no coincidieran, htmx anidaria
    # el formulario dentro de si mismo en cada envio fallido.
    assert 'hx-target="#tt-survey-form"' in cuerpo
    assert 'hx-swap="outerHTML"' in cuerpo
    # Paso 0 de 2: el boton de avance, no el de envio (Tarea 3).
    assert "Siguiente" in cuerpo
    assert "Enviar respuestas" not in cuerpo


def test_el_campo_condicional_publica_su_visible_when(
    client_as, make_student, make_survey_form,
):
    """`relacion_carrera` solo aplica a quien trabaja: el JSON viaja al cliente.

    El servidor lo re-evalua igual (`is_visible`), asi que esto es para que la
    pregunta no se vea cuando no toca — no es la defensa.

    Tarea 2: esto no prueba el camino anonimo, asi que en vez de anonimizar el
    formulario se le da sesion (la fabrica ya es no-anonima por omision).
    """
    make_survey_form()

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    m = re.search(r'data-tt-field="relacion_carrera"[^>]*data-tt-when=\'([^\']+)\'', cuerpo)
    assert m, "el campo condicional no publica su `visible_when`"
    assert "situacion_laboral" in m.group(1) and "empleado" in m.group(1)


def test_la_escala_se_pinta_como_grupo_de_radios_con_sus_etiquetas(
    client_as, make_student, make_survey_form,
):
    """Un `scale` 1-5 son cinco radios con el mismo `name` y sus dos extremos.

    Sin las etiquetas de los extremos, un 1 y un 5 no significan nada: el
    visitante no sabe cual punta es "nada" y cual es "totalmente".

    Tarea 2: sesion real, no el camino anonimo (irrelevante para este render).
    """
    make_survey_form()

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    bloque = re.search(r'data-tt-field="relacion_carrera".*?</div>\s*</div>',
                       cuerpo, flags=re.S)
    assert bloque, "no se renderizo el campo de escala"
    trozo = bloque.group(0)
    for n in range(1, 6):
        assert f'name="relacion_carrera" value="{n}"' in trozo, f"falta el punto {n}"
    assert 'value="0"' not in trozo and 'value="6"' not in trozo
    assert "Nada relacionado" in trozo
    assert "Totalmente relacionado" in trozo
    assert 'role="radiogroup"' in trozo


def test_la_trampa_va_fuera_de_pantalla_y_nunca_es_hidden(
    client_as, make_student, make_survey_form,
):
    """`type=hidden` y `display:none` los salta un bot serio; `left:-9999px` no.

    La clase es `tt-public-hp`, la que public.css define desde la Tarea 11 —no
    una nueva—: una clase sin regla dejaria la trampa VISIBLE en medio del
    cuestionario, que es peor que no tenerla.

    Tarea 2: el campo trampa se renderiza igual con o sin sesion (esta fuera
    del `{% if is_authenticated %}`); se usa sesion real por no ser esto una
    prueba del camino anonimo.
    """
    make_survey_form()

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    m = re.search(r'<input[^>]*name="website"[^>]*>', cuerpo)
    assert m, "no hay campo trampa"
    assert 'type="text"' in m.group(0), m.group(0)
    assert "hidden" not in m.group(0), m.group(0)
    assert "tt-public-hp" in cuerpo, "la trampa usa una clase que public.css no define"


def test_el_formulario_no_pide_numero_de_control(
    client_as, make_student, make_survey_form,
):
    """D1: jamas se acredita por numero de control auto-declarado.

    El servicio lo COPIA del usuario en sesion. Un campo asi en la pagina invita
    a escribirlo, y quien lo escriba creera que su respuesta acredita.

    Tarea 2: sesion real -no es este el test del camino anonimo-.
    """
    make_survey_form()

    resp = client_as(make_student()).get(SURVEY_URL, follow_redirects=False)

    # Las dos aserciones de fondo son `not in` y pasarian EN VACIO mientras la
    # ruta no exista (un 404 tampoco pide numero de control). Primero se exige
    # que HAYA cuestionario que juzgar.
    assert resp.status_code == 200, resp.text[:300]
    cuerpo = resp.text
    assert 'id="tt-survey-form"' in cuerpo
    assert 'name="control_number"' not in cuerpo
    assert 'name="numero_control"' not in cuerpo


def test_la_pagina_no_pasa_objetos_orm_a_la_plantilla(
    client_as, make_student, make_survey_form, monkeypatch,
):
    """Un objeto ORM en el contexto renderiza VERDE aqui y revienta en produccion.

    `conftest._TestSession.close()` es un no-op deliberado, asi que la sesion de
    la ruta nunca se cierra de verdad y nada se desasocia: un `DetachedInstance
    Error` es INVISIBLE para este arnes. Por eso no se mide el render, se mide
    la FORMA del contexto.

    Tarea 2: sesion real. La fuga de ORM que este test vigila puede colarse por
    el camino del borrador (`SurveyService.get_draft`), que solo se ejercita
    con `user` presente -anonimo lo dejaria sin probar, no solo "sin sesion".
    """
    from itcj2.apps.titulatec.pages import public as mod
    from tests.fastapi.titulatec.test_survey_submit_routes import orm_en

    make_survey_form()
    visto = {}
    real = mod.render_titulatec

    def espia(request, template, context=None, *a, **kw):
        visto["ctx"] = context
        return real(request, template, context, *a, **kw)

    monkeypatch.setattr(mod, "render_titulatec", espia)

    resp = client_as(make_student()).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200
    sucios = orm_en(visto["ctx"])
    assert sucios == [], f"objetos ORM en el contexto: {sucios}"


# ---------------------------------------------------------------------------
# Los OCHO tipos de campo, no solo los cuatro del schema por omision
# ---------------------------------------------------------------------------
# `SURVEY_SCHEMA_V1` (conftest) ejercita radio, scale, multiselect y textarea.
# Los otros cuatro -text, select, checkbox y yesno- quedarian sin renderizar
# nunca en la suite, y el motor de encuestas los admite: el dia que un seeder
# declare un `yesno`, la pregunta saldria en blanco y nadie lo sabria hasta que
# un egresado la viera.
SCHEMA_OCHO_TIPOS = {
    "enabled": True,
    "sections": [{"key": "todo", "title": "Todos los tipos"}],
    "fields": [
        {"key": "nombre_corto", "section": "todo", "type": "text",
         "label": "Texto corto", "required": False,
         "validation": {"maxLength": 80}},
        {"key": "comentarios", "section": "todo", "type": "textarea",
         "label": "Texto largo", "required": False,
         "validation": {"maxLength": 500}},
        {"key": "turno", "section": "todo", "type": "select",
         "label": "Turno del empleo", "required": False,
         "options": [{"value": "matutino", "label": "Matutino"},
                     {"value": "vespertino", "label": "Vespertino"}]},
        {"key": "situacion_laboral", "section": "todo", "type": "radio",
         "label": "Situacion laboral", "required": False,
         "options": [{"value": "empleado", "label": "Trabajando"},
                     {"value": "buscando", "label": "Buscando empleo"}]},
        {"key": "areas_fuertes", "section": "todo", "type": "multiselect",
         "label": "Areas mas fuertes", "required": False,
         "options": [{"value": "tecnica", "label": "Formacion tecnica"},
                     {"value": "idiomas", "label": "Idiomas"}]},
        {"key": "acepta_contacto", "section": "todo", "type": "checkbox",
         "label": "Acepto que me contacten", "required": False},
        {"key": "recomendarias", "section": "todo", "type": "yesno",
         "label": "Recomendarias el Tec?", "required": False},
        {"key": "relacion_carrera", "section": "todo", "type": "scale",
         "label": "Relacion con tu carrera", "required": False,
         "scale": {"min": 1, "max": 5,
                   "min_label": "Nada", "max_label": "Totalmente"}},
    ],
}


def test_el_formulario_pinta_los_ocho_tipos_de_campo(
    client_as, make_student, make_survey_form,
):
    """Cada tipo declarado en `FIELD_TYPES` tiene que salir con SU control.

    Tarea 2: sesion real (irrelevante para el render de tipos de campo).
    """
    make_survey_form(schema=SCHEMA_OCHO_TIPOS)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    assert 'type="text" id="f-nombre_corto"' in cuerpo
    assert 'id="f-comentarios"' in cuerpo and "<textarea" in cuerpo
    assert 'form-select" id="f-turno"' in cuerpo
    assert 'value="matutino"' in cuerpo
    assert 'type="radio" id="f-situacion_laboral-1"' in cuerpo
    assert 'type="checkbox" id="f-areas_fuertes-1"' in cuerpo
    assert 'type="checkbox" id="f-acepta_contacto"' in cuerpo
    assert 'id="f-recomendarias-si"' in cuerpo and 'id="f-recomendarias-no"' in cuerpo
    assert 'name="relacion_carrera" value="5"' in cuerpo
    # Ninguno se quedo sin pintar: los ocho tienen su envoltorio.
    for llave in ("nombre_corto", "comentarios", "turno", "situacion_laboral",
                  "areas_fuertes", "acepta_contacto", "recomendarias",
                  "relacion_carrera"):
        assert 'data-tt-field="%s"' % llave in cuerpo, "falta el campo " + llave


def test_el_re_render_conserva_el_yesno_la_casilla_y_el_select(
    client_as, make_student, make_survey_form, db_session,
):
    """El `yesno` es el que rompe si nadie normaliza para pintar.

    Del navegador llega `"si"`, no `True`. La plantilla compara contra un
    booleano (que es la forma que tiene ese campo en el borrador y en
    `answers`), asi que sin el puente de `_display_values` los dos radios vuelven
    VACIOS: el visitante corrige el texto y descubre que se le borro la pregunta
    de al lado. Falla en silencio y solo en el camino de error.

    Tarea 2: sesion real -esto prueba el re-render en el error de validacion,
    no el camino anonimo-.
    """
    from itcj2.apps.titulatec.models import SurveyResponse

    make_survey_form(schema=SCHEMA_OCHO_TIPOS)
    payload = {
        "website": "",
        "nombre_corto": "n" * 120,          # maxLength 80 -> falla aqui
        "turno": "vespertino",
        "acepta_contacto": "1",
        "recomendarias": "si",
        "relacion_carrera": "3",
    }

    resp = client_as(make_student()).post(
        SURVEY_URL, data=payload,
        headers={"X-Real-IP": "203.0.113.41"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert db_session.query(SurveyResponse).count() == 0
    cuerpo = resp.text
    assert re.search(r'id="f-recomendarias-si"[^>]*\schecked', cuerpo), \
        "el `yesno` volvio en blanco"
    assert not re.search(r'id="f-recomendarias-no"[^>]*\schecked', cuerpo)
    assert re.search(r'id="f-acepta_contacto"[^>]*\schecked', cuerpo), \
        "la casilla volvio en blanco"
    assert 'value="vespertino" selected' in cuerpo, "el select volvio en blanco"
    assert re.search(r'name="relacion_carrera" value="3"[^>]*\schecked', cuerpo)


def test_el_borrador_vuelve_marcado_aunque_guarde_tipos_y_no_texto(
    client_as, make_student, make_survey_form, db_session,
):
    """Un borrador puede traer el valor TIPADO, no la cadena del navegador.

    Es la forma que tiene `answers` en `titulatec_survey_responses` (la
    proyeccion validada: `True`, `3`, `["tecnica"]`), asi que cualquier productor
    que reutilice esa forma -un prellenado, un import, una version futura del
    autoguardado- la deja asi en el borrador. Comparar `3` con `"3"` en la
    plantilla da falso y la escala vuelve sin marcar, sin error y sin rastro.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(schema=SCHEMA_OCHO_TIPOS)
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id, answers={
        "relacion_carrera": 3, "recomendarias": True,
        "acepta_contacto": True, "areas_fuertes": ["idiomas"],
    }))
    db_session.flush()

    cuerpo = client_as(student).get(SURVEY_URL, follow_redirects=False).text

    assert re.search(r'name="relacion_carrera" value="3"[^>]*\schecked', cuerpo), \
        "la escala del borrador no vuelve marcada"
    assert re.search(r'id="f-recomendarias-si"[^>]*\schecked', cuerpo)
    assert re.search(r'id="f-acepta_contacto"[^>]*\schecked', cuerpo)
    assert re.search(r'value="idiomas"[^>]*\schecked', cuerpo)


SCHEMA_SECCION_FANTASMA = {
    "enabled": True,
    "sections": [{"key": "empleo", "title": "Situacion laboral"}],
    "fields": [
        # `required=True` (Tarea 3, ronda 2): con las dos preguntas opcionales,
        # `_start_step` no encontraria ningun obligatorio sin contestar en
        # NINGUNA seccion y la carga inicial aterrizaria de una vez en el
        # grupo suelto -justo lo que esta prueba no quiere medir-. Obligatoria
        # mantiene a "empleo" como el paso de arranque, que es lo que hace
        # que `situacion_laboral` siga siendo el control vivo que se compara.
        {"key": "situacion_laboral", "section": "empleo", "type": "radio",
         "label": "Situacion laboral", "required": True,
         "options": [{"value": "empleado", "label": "Trabajando"}]},
        # Apunta a una seccion que NO esta declarada: erratas asi las escribe
        # el seeder a mano y no hay quien las valide al vuelo.
        {"key": "comentarios", "section": "opinionn", "type": "textarea",
         "label": "Comentarios", "required": False,
         "validation": {"maxLength": 500}},
    ],
}


def test_un_campo_con_seccion_inexistente_igual_se_pinta(
    client_as, make_student, make_survey_form,
):
    """Una llave mal escrita en el seeder NO puede tragarse una pregunta.

    Si el campo desapareciera del formulario, nadie lo notaria: la encuesta se
    veria bien, se contestaria entera y la columna saldria vacia en el export
    de los 400 egresados.

    Tarea 2: sesion real (irrelevante para el agrupado por seccion).

    Tarea 3: el grupo suelto ("_") es su PROPIO paso, distinto del de
    "empleo" -son dos secciones, y el asistente pinta una a la vez-, asi que
    `comentarios` ya no esta en la misma pantalla que `situacion_laboral`.
    Se comprueba que sigue existiendo AVANZANDO un paso, no en el HTML de la
    carga inicial: la pregunta no se perdio, vive en el paso siguiente.
    """
    make_survey_form(schema=SCHEMA_SECCION_FANTASMA)
    c = client_as(make_student())

    primero = c.get(SURVEY_URL, follow_redirects=False).text
    assert 'data-tt-field="situacion_laboral"' in primero
    assert 'data-tt-field="comentarios"' not in primero   # esta en el paso 2, no en este

    # `comentarios` es opcional: avanzar contestando solo el obligatorio de
    # "empleo" es valido.
    segundo = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                                     "situacion_laboral": "empleado"},
                     follow_redirects=False).text
    assert 'data-tt-field="comentarios"' in segundo, \
        "la pregunta con la seccion mal escrita se perdio del formulario"


def test_los_campos_escalares_tienen_nombre_accesible(
    client_as, make_student, make_survey_form,
):
    """La pregunta es un `<span>`, no un `<label for>`: hay que apuntarla.

    Los tipos agrupados (`radio`, `multiselect`, `yesno`, `scale`) ya la
    referencian desde su `role="radiogroup"`/`role="group"`. Los tres escalares
    —`text`, `textarea`, `select`— no emitian `<label for>`, ni
    `aria-labelledby`, ni `aria-label`: un lector de pantalla anuncia
    "cuadro de edicion, en blanco" y la pregunta no se oye. WCAG 1.3.1 y 4.1.2,
    en una pagina publica para una generacion entera.

    Tarea 2: sesion real (irrelevante para el nombre accesible del control).
    """
    make_survey_form(schema=SCHEMA_OCHO_TIPOS)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    for llave in ("nombre_corto", "comentarios", "turno"):
        control = re.search(
            r'<(input|textarea|select)\b[^>]*id="f-%s"[^>]*>' % llave, cuerpo)
        assert control, "no se encontro el control de " + llave
        etiqueta = control.group(0)
        tiene_nombre = ('aria-labelledby="f-%s-lbl"' % llave in etiqueta
                        or "aria-label=" in etiqueta)
        assert tiene_nombre, (
            "%s no tiene nombre accesible: %r" % (llave, etiqueta))
        # Y el id al que apunta existe de verdad en la pagina.
        assert 'id="f-%s-lbl"' % llave in cuerpo


# ---------------------------------------------------------------------------
# Tarea 2: `SurveyForm.is_anonymous` decide si la encuesta exige sesion
# ---------------------------------------------------------------------------
def test_sin_sesion_un_formulario_no_anonimo_manda_al_login_con_next(
    client, db_session, make_survey_form,
):
    make_survey_form(is_anonymous=False)
    resp = client.get("/titulatec/encuesta-egresados", follow_redirects=False)
    assert resp.status_code in (302, 303), resp.text[:300]
    destino = resp.headers["location"]
    assert destino.startswith("/itcj/login")
    assert "next=" in destino
    assert "encuesta-egresados" in destino


def test_sin_sesion_un_formulario_anonimo_sigue_abriendo(
    client, db_session, make_survey_form,
):
    """La capacidad anonima se conserva: la columna decide, no la ruta."""
    make_survey_form(is_anonymous=True)
    resp = client.get("/titulatec/encuesta-egresados")
    assert resp.status_code == 200


def test_el_envio_sin_sesion_a_un_formulario_no_anonimo_no_escribe(
    client, db_session, make_survey_form,
):
    from itcj2.apps.titulatec.models import SurveyResponse
    form = make_survey_form(is_anonymous=False)
    antes = db_session.query(SurveyResponse).filter_by(form_id=form.id).count()
    resp = client.post("/titulatec/encuesta-egresados",
                       data={"situacion_laboral": "empleado"},
                       follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)
    db_session.expire_all()
    assert db_session.query(SurveyResponse).filter_by(form_id=form.id).count() == antes


def test_el_borrador_sin_sesion_a_un_formulario_no_anonimo_no_escribe(
    client, db_session, make_survey_form,
):
    from itcj2.apps.titulatec.models import SurveyDraft
    form = make_survey_form(is_anonymous=False)
    resp = client.post("/titulatec/encuesta-egresados/borrador",
                       data={"situacion_laboral": "empleado"},
                       follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403, 204)
    db_session.expire_all()
    assert db_session.query(SurveyDraft).filter_by(form_id=form.id).count() == 0
