"""Tarea 3: el formulario de la encuesta se recorre por pasos, no apilado.

Hoy `survey_form.html` pinta `{% for sec in sections %}` con TODAS las
secciones una detras de otra; esta tarea convierte cada seccion en un PASO
navegable, con una ruta nueva (`STEP_URL`) que avanza o retrocede.

Reglas del spec (3.3 y 5) que estas pruebas miden:
  * Hacia adelante es ESTRICTO: no se avanza con errores en la seccion actual.
  * Hacia atras es LIBRE: se puede volver a cualquier seccion ya visitada, sin
    validar, y sin borrar lo capturado en secciones posteriores.
  * Una seccion cuyos campos quedan TODOS invisibles se salta, en los dos
    sentidos.
  * El envio final (`SURVEY_URL`, la ruta que ya existia) revalida el
    formulario ENTERO, no solo el ultimo paso.
  * El estado del recorrido viaja en las respuestas acumuladas -que ya viajan
    completas en cada envio, como ocultos por cada campo que no es del paso
    actual- mas el indice del paso (`tt_step`). Nada de sesion de servidor.

`SCHEMA_TRES_PASOS` (propio de este archivo, no `SURVEY_SCHEMA_V1` de
`conftest.py`) declara TRES secciones:
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

    resp = c.post(STEP_URL, data={"tt_step": "2", "tt_back": "1",
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

    # Retrocede dos veces: de 'tres' a 'dos', y de 'dos' a 'uno'.
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_back": "1",
                               "nombre": "Ana", "estudia": "si", "trabaja": "si",
                               "escuela": "ITCJ"},
              follow_redirects=False)
    assert 'data-tt-section="dos"' in r.text
    assert re.search(r'name="escuela"[^>]*\bvalue="ITCJ"', r.text), \
        "lo capturado en 'dos' se perdio al volver un paso"

    r = c.post(STEP_URL, data={"tt_step": "1", "tt_back": "1",
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
    r = c.post(STEP_URL, data={"tt_step": "2", "tt_back": "1",
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
