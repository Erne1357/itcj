"""Tarea 3: el formulario de la encuesta se recorre por pasos, no apilado.

Hoy `survey_form.html` pinta `{% for sec in sections %}` con TODAS las
secciones una detras de otra; esta tarea convierte cada seccion en un PASO
navegable, con una ruta nueva (`STEP_URL`) que avanza o retrocede.

Reglas del spec (3.3 y 5) que estas pruebas miden:
  * Hacia adelante es ESTRICTO: no se avanza con errores en la seccion actual,
    y ni siquiera un `tt_goto` hacia un paso por delante lo salta (el servidor
    decide el destino de un avance, nunca el cliente).
  * Hacia atras es LIBRE y DIRECTO (ronda 2, pedido del controlador): un
    `tt_goto=<indice>` alcanza cualquier seccion YA VISITADA de un solo golpe
    -no hace falta retroceder de a un paso-, sin validar, y sin borrar lo
    capturado en secciones posteriores (ni siquiera en las que el salto
    "pasa de largo").
  * Una seccion cuyos campos quedan TODOS invisibles se salta, en los dos
    sentidos.
  * El envio final (`SURVEY_URL`, la ruta que ya existia) revalida el
    formulario ENTERO, no solo el ultimo paso.
  * El estado del recorrido viaja en las respuestas acumuladas -que ya viajan
    completas en cada envio, como ocultos por cada campo que no es del paso
    actual- mas el indice del paso (`tt_step`). Nada de sesion de servidor.
  * La carga inicial (GET) reanuda en el primer paso con un obligatorio
    VISIBLE sin contestar (`_start_step`), o en el ultimo si el borrador ya
    los cubre todos -tambien derivado de lo que ya existe, sin sesion nueva-.

`SCHEMA_TRES_PASOS` (propio de este archivo, no `SURVEY_SCHEMA_V1` de
`conftest.py`, y tampoco el instrumento real de 63 preguntas que ya vive
sembrado en la base de dev bajo el mismo `code="egresados"`: cada prueba
siembra su PROPIO esquema via `make_survey_form(schema=...)`, que cierra y
sustituye cualquier version abierta) declara TRES secciones:
  * `uno`    -> nombre, estudia, trabaja (siempre visibles; son las FUENTES).
  * `dos`    -> escuela (visible solo si `estudia == "si"`).
  * `tres`   -> empresa (visible solo si `trabaja == "si"`) + comentario
                (siempre visible, para que `tres` nunca se quede sin campos
                visibles y por tanto SIEMPRE sea un paso alcanzable donde
                probar la obligatoriedad condicional de `empresa`).

Con esto, `dos` es la seccion que se salta (su UNICO campo depende de `uno`) y
`tres` -la TERCERA- depende de una respuesta de la PRIMERA (`trabaja`), que es
justo la forma de esquema que pide el brief.

Todas usan `client_as(make_student())`: la politica de sesion (Tarea 2) es
ortogonal a esto, y la fabrica de formularios ya es no-anonima por omision.
"""
from __future__ import annotations

import re

SURVEY_URL = "/titulatec/encuesta-egresados"
STEP_URL = "/titulatec/encuesta-egresados/paso"

SCHEMA_TRES_PASOS = {
    "enabled": True,
    "sections": [
        {"key": "uno", "title": "Datos generales"},
        {"key": "dos", "title": "Escuela"},
        {"key": "tres", "title": "Empleo"},
    ],
    "fields": [
        {"key": "nombre", "section": "uno", "type": "text",
         "label": "Tu nombre completo", "required": True,
         "validation": {"maxLength": 80}},
        {"key": "estudia", "section": "uno", "type": "radio",
         "label": "Sigues estudiando actualmente?", "required": True,
         "options": [{"value": "si", "label": "Si"}, {"value": "no", "label": "No"}]},
        {"key": "trabaja", "section": "uno", "type": "radio",
         "label": "Trabajas actualmente?", "required": True,
         "options": [{"value": "si", "label": "Si"}, {"value": "no", "label": "No"}]},
        {"key": "escuela", "section": "dos", "type": "text",
         "label": "Nombre de tu escuela", "required": True,
         "validation": {"maxLength": 120},
         "visible_when": {"estudia": "si"}},
        {"key": "empresa", "section": "tres", "type": "text",
         "label": "Nombre de tu empresa", "required": True,
         "validation": {"maxLength": 120},
         "visible_when": {"trabaja": "si"}},
        {"key": "comentario", "section": "tres", "type": "textarea",
         "label": "Algo mas que quieras contarnos?", "required": False,
         "validation": {"maxLength": 500}},
    ],
}


def _campo(cuerpo: str, key: str) -> str:
    """Bloque `<div data-tt-field="key">...</div>` completo, para mirar su `aria-invalid`."""
    m = re.search(r'data-tt-field="%s".*?</div>\s*</div>' % re.escape(key), cuerpo, flags=re.S)
    return m.group(0) if m else ""


def test_la_primera_carga_muestra_solo_la_primera_seccion(
    client_as, make_student, make_survey_form,
):
    """El resto de secciones no esta en el HTML, no solo oculto por CSS."""
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    assert 'data-tt-section="uno"' in cuerpo
    assert 'data-tt-field="nombre"' in cuerpo
    assert 'data-tt-field="estudia"' in cuerpo
    assert 'data-tt-field="trabaja"' in cuerpo

    assert 'data-tt-section="dos"' not in cuerpo
    assert 'data-tt-section="tres"' not in cuerpo
    assert 'data-tt-field="escuela"' not in cuerpo
    assert 'data-tt-field="empresa"' not in cuerpo
    assert 'data-tt-field="comentario"' not in cuerpo
    # Ni siquiera como oculto: recien cargada, todavia no hay nada que preservar.
    assert 'name="escuela"' not in cuerpo
    assert 'name="empresa"' not in cuerpo

    # El indice del paso viaja en el propio formulario, para la ruta de avance.
    assert 'name="tt_step" value="0"' in cuerpo
    assert "Paso 1 de" in cuerpo


def test_avanzar_con_un_obligatorio_vacio_devuelve_el_mismo_paso_con_el_error(
    client_as, make_student, make_survey_form,
):
    """Y el error viaja en data-tt-error con el aria-invalid en el control."""
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "0", "tt_next": "1",
                        "nombre": "", "estudia": "si", "trabaja": "si"},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    cuerpo = resp.text
    assert 'data-tt-section="uno"' in cuerpo            # el MISMO paso
    assert 'data-tt-section="dos"' not in cuerpo         # no avanzo
    assert 'data-tt-error="nombre"' in cuerpo
    assert 'aria-invalid="true"' in _campo(cuerpo, "nombre")


def test_avanzar_completo_entrega_la_siguiente_seccion(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "0", "tt_next": "1",
                        "nombre": "Ana", "estudia": "si", "trabaja": "si"},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    cuerpo = resp.text
    assert 'data-tt-section="dos"' in cuerpo
    assert 'data-tt-field="escuela"' in cuerpo
    assert 'data-tt-section="uno"' not in cuerpo
    # Lo contestado en el paso 1 no desaparece: viaja oculto para el envio final
    # y para que un futuro "Atras" lo recupere.
    assert 'name="nombre" value="Ana"' in cuerpo
    assert 'name="estudia" value="si"' in cuerpo
    assert 'name="trabaja" value="si"' in cuerpo
    assert "Paso 2 de" in cuerpo


def test_una_seccion_sin_campos_visibles_se_salta_hacia_adelante(
    client_as, make_student, make_survey_form,
):
    """Con `estudia=no`, la seccion 'dos' (escuela) se queda sin campos visibles."""
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "0", "tt_next": "1",
                        "nombre": "Ana", "estudia": "no", "trabaja": "si"},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    cuerpo = resp.text
    assert 'data-tt-section="dos"' not in cuerpo, "la seccion invisible no deberia mostrarse"
    assert 'data-tt-field="escuela"' not in cuerpo
    assert 'data-tt-section="tres"' in cuerpo, "se tuvo que saltar 'dos' y caer en 'tres'"
    assert 'data-tt-field="empresa"' in cuerpo


def test_una_seccion_sin_campos_visibles_se_salta_hacia_atras(
    client_as, make_student, make_survey_form,
):
    """Simetrico al anterior: retroceder desde 'tres' salta 'dos' y cae en 'uno'."""
    make_survey_form(schema=SCHEMA_TRES_PASOS)
    c = client_as(make_student())

    # Llega a 'tres' saltandose 'dos' (estudia=no), igual que la prueba anterior.
    avance = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                                    "nombre": "Ana", "estudia": "no", "trabaja": "si"},
                    follow_redirects=False)
    assert 'data-tt-section="tres"' in avance.text

    resp = c.post(STEP_URL, data={"tt_step": "2", "tt_goto": "0",
                                  "nombre": "Ana", "estudia": "no", "trabaja": "si"},
                 follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    cuerpo = resp.text
    assert 'data-tt-section="dos"' not in cuerpo, "retroceder no deberia mostrar la invisible"
    assert 'data-tt-section="uno"' in cuerpo, "se tuvo que saltar 'dos' hacia atras y caer en 'uno'"


def test_retroceder_no_borra_lo_capturado_en_pasos_posteriores(
    client_as, make_student, make_survey_form,
):
    """Ir y venir entre pasos no pierde lo que ya se habia contestado adelante."""
    make_survey_form(schema=SCHEMA_TRES_PASOS)
    c = client_as(make_student())

    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text

    r = c.post(STEP_URL, data={"tt_step": "1", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text

    # Retrocede dos veces, de a un paso: de 'tres' a 'dos', y de 'dos' a 'uno'.
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_goto": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text
    assert re.search(r'name="escuela"[^>]*\bvalue="ITCJ"', r.text), \
        "lo capturado en 'dos' se perdio al volver un paso"

    r = c.post(STEP_URL, data={"tt_step": "1", "tt_goto": "0",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="uno"' in r.text

    # Y avanza de nuevo: lo de 'dos' -mas adelante que 'uno'- sigue ahi.
    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text
    assert re.search(r'name="escuela"[^>]*\bvalue="ITCJ"', r.text), \
        "retroceder hasta el paso 1 y avanzar borro lo capturado en 'dos'"


def test_el_envio_final_revalida_todo_no_solo_el_ultimo_paso(
    client_as, make_student, make_survey_form, db_session,
):
    """Completa los 3 pasos, retrocede al 1, cambia la respuesta que gobierna
    la condicion del 3, envia: el envio tiene que rechazar, no aceptar."""
    from itcj2.apps.titulatec.models import SurveyResponse

    make_survey_form(schema=SCHEMA_TRES_PASOS)
    c = client_as(make_student())

    # 1) `trabaja=no`: 'empresa' nace invisible. `estudia=no` salta 'dos', asi
    #    que el recorrido completo hoy es uno -> tres.
    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "no", "trabaja": "no"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text

    # 2) Se completa 'tres' (solo 'comentario' es visible y es opcional): es el
    #    ULTIMO paso alcanzable -> se ofrece "Enviar respuestas", no "Siguiente".
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_next": "1",
                               "nombre": "Ana", "estudia": "no", "trabaja": "no",
                               "comentario": "Todo bien"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text
    assert "Enviar respuestas" in r.text

    # 3) Retrocede a la primera seccion (salta 'dos', que sigue invisible).
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_goto": "0",
                               "nombre": "Ana", "estudia": "no", "trabaja": "no",
                               "comentario": "Todo bien"},
              follow_redirects=False)
    assert 'data-tt-section="uno"' in r.text

    # 4) Cambia la respuesta que gobierna la condicion del 3: `trabaja` pasa a
    #    "si". 'empresa' se vuelve visible Y obligatoria, y sigue sin contestar.
    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "no", "trabaja": "si",
                               "comentario": "Todo bien"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text, "trabaja=si sigue saltando 'dos' (estudia=no)"
    assert "Enviar respuestas" in r.text

    # 5) Envia con el estado acumulado en ese momento -sin 'empresa'-, tal como
    #    lo mandaria el formulario real (ocultos + lo visible del ultimo paso).
    resp = c.post(SURVEY_URL, data={"website": "", "nombre": "Ana", "estudia": "no",
                                    "trabaja": "si", "comentario": "Todo bien"},
                 headers={"X-Real-IP": "203.0.113.77"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert db_session.query(SurveyResponse).count() == 0, \
        "el envio final tuvo que rechazar, no aceptar"
    assert 'data-tt-error="empresa"' in resp.text


def test_un_campo_condicional_obligatorio_se_exige_cuando_es_visible(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "2", "tt_next": "1",
                        "nombre": "Ana", "estudia": "no", "trabaja": "si",
                        "empresa": "", "comentario": ""},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-error="empresa"' in resp.text
    assert 'data-tt-section="tres"' in resp.text        # se quedo en el mismo paso


def test_un_campo_condicional_obligatorio_no_se_exige_cuando_no_lo_es(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "2", "tt_next": "1",
                        "nombre": "Ana", "estudia": "no", "trabaja": "no",
                        "empresa": "", "comentario": ""},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-error="empresa"' not in resp.text
    assert "data-tt-errors" not in resp.text


# ---------------------------------------------------------------------------
# Ronda 2 (pedido del controlador): la GET reanuda donde se quedo, y el
# retroceso es directo -no de a un paso- via `tt_goto`.
# ---------------------------------------------------------------------------
def test_un_borrador_a_medias_abre_en_el_primer_paso_incompleto(
    client_as, make_student, make_survey_form, db_session,
):
    """No en el paso 0: en el primero cuyo obligatorio VISIBLE sigue vacio.

    `uno` esta completo (nombre/estudia/trabaja contestados). Con
    `estudia=si`, `escuela` (en 'dos') es visible y obligatoria, y el
    borrador no la trae -> `_start_step` tiene que aterrizar ahi, no en 'uno'.
    `trabaja=no` deja 'empresa' invisible (no obligatoria todavia), asi que
    'tres' no compite por ser el paso incompleto.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(schema=SCHEMA_TRES_PASOS)
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id, answers={
        "nombre": "Ana", "estudia": "si", "trabaja": "no",
    }))
    db_session.flush()

    cuerpo = client_as(student).get(SURVEY_URL, follow_redirects=False).text

    assert 'data-tt-section="dos"' in cuerpo, \
        "tenia que reanudar en 'dos', el primer paso con un obligatorio vacio"
    assert 'data-tt-section="uno"' not in cuerpo


def test_un_borrador_completo_abre_en_el_ultimo_paso(
    client_as, make_student, make_survey_form, db_session,
):
    """Si el borrador ya cubre todos los obligatorios visibles, al ultimo paso.

    `estudia=si` y `trabaja=si` hacen visibles las TRES secciones, y el
    borrador contesta los tres obligatorios (`escuela`, `empresa` incluidos):
    no hay nada que reanudar, asi que aterriza en 'tres' -a un click de
    "Enviar respuestas"-.
    """
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(schema=SCHEMA_TRES_PASOS)
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id, answers={
        "nombre": "Ana", "estudia": "si", "trabaja": "si",
        "escuela": "ITCJ", "empresa": "ITCJ Corp",
    }))
    db_session.flush()

    cuerpo = client_as(student).get(SURVEY_URL, follow_redirects=False).text

    assert 'data-tt-section="tres"' in cuerpo
    assert 'data-tt-section="uno"' not in cuerpo
    assert 'data-tt-section="dos"' not in cuerpo
    assert "Enviar respuestas" in cuerpo


def test_un_paso_ya_visitado_es_alcanzable_de_un_solo_salto(
    client_as, make_student, make_survey_form,
):
    """El indicador de progreso llega directo: no hace falta un click por paso.

    Las tres secciones quedan visibles (`estudia=si`, `trabaja=si`), asi que
    el salto de 'tres' a 'uno' cruza 'dos' de un solo golpe -no es un salto de
    seccion invisible, que ya cubre otra prueba-.
    """
    make_survey_form(schema=SCHEMA_TRES_PASOS)
    c = client_as(make_student())

    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text

    r = c.post(STEP_URL, data={"tt_step": "1", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text

    resp = c.post(STEP_URL, data={"tt_step": "2", "tt_goto": "0",
                                  "nombre": "Ana", "estudia": "si", "trabaja": "si",
                                  "escuela": "ITCJ"},
                 follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-section="uno"' in resp.text, \
        "'uno' (visitado) tenia que alcanzarse de un solo salto desde 'tres'"


def test_un_paso_por_delante_no_es_alcanzable_de_un_salto(
    client_as, make_student, make_survey_form,
):
    """El salto directo es SOLO hacia atras: adelante sigue siendo estricto.

    Se pide `tt_goto=2` (un paso por delante del actual, `tt_step=0`) con los
    obligatorios de 'uno' vacios a proposito: si el salto se concediera sin
    mas, 'tres' se veria aunque 'uno' ni siquiera pasara su propia validacion.
    """
    make_survey_form(schema=SCHEMA_TRES_PASOS)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "0", "tt_goto": "2",
                        "nombre": "", "estudia": "", "trabaja": ""},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-section="uno"' in resp.text, \
        "un tt_goto hacia adelante no deberia mover el paso"
    assert 'data-tt-section="tres"' not in resp.text


def test_saltar_hacia_atras_de_un_golpe_no_pierde_lo_de_en_medio(
    client_as, make_student, make_survey_form,
):
    """El invariante mas facil de romper al tocar navegacion: tambien aguanta
    un salto directo, no solo el retroceso de a un paso.
    """
    make_survey_form(schema=SCHEMA_TRES_PASOS)
    c = client_as(make_student())

    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text

    r = c.post(STEP_URL, data={"tt_step": "1", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="tres"' in r.text

    # Salto DIRECTO de 'tres' (indice 2) a 'uno' (indice 0): cruza 'dos' sin
    # detenerse ahi en el camino de vuelta.
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_goto": "0",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="uno"' in r.text

    # Avanza de nuevo: lo de 'dos' -por donde el salto paso de largo- sigue ahi.
    r = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text
    assert re.search(r'name="escuela"[^>]*\bvalue="ITCJ"', r.text), \
        "el salto directo hacia atras borro lo capturado en la seccion que salto"
