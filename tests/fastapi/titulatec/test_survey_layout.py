"""Encuesta de egresados: contrato de MARCADO del rediseno (riel de pasos + tarjetas).

`test_public_survey_routes.py` y `test_survey_steps.py` fijan el COMPORTAMIENTO
(que se pinta, que se valida, a donde se avanza). Este archivo fija la FORMA que
el rediseno de la pantalla le promete a la hoja de estilos, a `survey.js` y a
los E2E, y que ninguno de aquellos mide:

  * un `radio` con 20 o mas opciones se pinta como `<select>` con el MISMO
    `name` y los MISMOS `value` (servidor, borrador y validacion no cambian: un
    `""` de la opcion vacia es "sin contestar", igual que un radio sin marcar);
  * el indicador de pasos existe UNA sola vez en el DOM -riel en escritorio y
    chips en movil son el mismo nodo restilizado por CSS; duplicarlo rompe el
    modo estricto de `locator('.tt-steps-item .tt-steps-link')`-, con el paso
    actual marcado por `aria-current="step"` y una barra de progreso nativa;
  * cada opcion de radio/multiselect/yesno/checkbox es una "tile": un `<label>`
    que ENVUELVE el input nativo visible;
  * los botones de la barra de acciones conservan su nombre accesible EXACTO
    aunque lleven icono;
  * el layout ancho entra por un modificador SOLO de la encuesta: la
    inscripcion comparte `base_public.html` y no debe cambiar ni un pixel.

Todas van con sesion (`client_as(make_student())`): la politica de sesion
(Tarea 2) es ortogonal a la forma, y la fabrica ya es no-anonima por omision.
"""
from __future__ import annotations

import re
from pathlib import Path

import itcj2

SURVEY_URL = "/titulatec/encuesta-egresados"
STEP_URL = f"{SURVEY_URL}/paso"

_APP_DIR = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"
PUBLIC_TPL = _APP_DIR / "templates" / "titulatec" / "public"
CSS_PUBLICO = _APP_DIR / "static" / "css" / "public.css"


def _opciones(n: int, prefijo: str) -> list[dict]:
    return [{"value": f"{prefijo}{i}", "label": f"Opcion {i}"} for i in range(1, n + 1)]


# Tres secciones: la minima forma de tener a la vez un paso visitado, el actual
# y uno por venir cuando se esta en el segundo.
SCHEMA_TRES = {
    "enabled": True,
    "sections": [
        {"key": "perfil", "title": "Perfil del egresado"},
        {"key": "empleo", "title": "Empleo actual"},
        {"key": "cierre", "title": "Comentarios finales"},
    ],
    "fields": [
        # 20 opciones: el umbral exacto a partir del cual deja de ser radio.
        {"key": "especialidad", "section": "perfil", "type": "radio",
         "label": "Especialidad", "required": True, "options": _opciones(20, "esp")},
        # 19: la frontera por debajo, sigue siendo radio.
        {"key": "carrera", "section": "perfil", "type": "radio",
         "label": "Carrera de egreso", "required": True, "options": _opciones(19, "car")},
        {"key": "empresa", "section": "empleo", "type": "text",
         "label": "Nombre de la empresa", "required": False,
         "validation": {"maxLength": 80}},
        {"key": "comentario", "section": "cierre", "type": "textarea",
         "label": "Comentario final", "required": False,
         "validation": {"maxLength": 200}},
    ],
}

# Un campo de cada tipo que pinta opciones, mas los que no, con listas de
# tamanos y largos de rotulo representativos del instrumento real.
SCHEMA_OPCIONES = {
    "enabled": True,
    "sections": [{"key": "todo", "title": "Todos los tipos"}],
    "fields": [
        {"key": "likert", "section": "todo", "type": "radio",
         "label": "Calidad de los docentes", "required": False,
         "options": [{"value": v, "label": v} for v in ("Muy buena", "Buena", "Regular", "Mala")]},
        {"key": "sexo", "section": "todo", "type": "radio",
         "label": "Sexo", "required": False,
         "options": [{"value": "H", "label": "Hombre"}, {"value": "M", "label": "Mujer"}]},
        {"key": "carrera_larga", "section": "todo", "type": "radio",
         "label": "Carrera", "required": False,
         "options": [{"value": f"c{i}", "label": f"Ing. en Sistemas Computacionales plan {i:02d}"}
                     for i in range(1, 17)]},
        {"key": "sector", "section": "todo", "type": "radio",
         "label": "Sector", "required": False,
         "options": [{"value": f"s{i}", "label": "Secundario (Industrial, construccion, transformacion, etc.)"}
                     for i in range(1, 5)]},
        {"key": "areas", "section": "todo", "type": "multiselect",
         "label": "Areas fuertes", "required": False,
         "options": [{"value": "tec", "label": "Tecnica"}, {"value": "idi", "label": "Idiomas"},
                     {"value": "pra", "label": "Practicas"}]},
        {"key": "recomienda", "section": "todo", "type": "yesno",
         "label": "Recomendarias el Tec?", "required": False},
        {"key": "contacto", "section": "todo", "type": "checkbox",
         "label": "Acepto que me contacten", "required": False},
        {"key": "relacion", "section": "todo", "type": "scale",
         "label": "Relacion con tu carrera", "required": False,
         "scale": {"min": 1, "max": 5, "min_label": "Poco", "max_label": "Mucho"}},
        {"key": "turno", "section": "todo", "type": "select",
         "label": "Turno", "required": False,
         "options": [{"value": "m", "label": "Matutino"}, {"value": "v", "label": "Vespertino"}]},
        {"key": "nombre", "section": "todo", "type": "text",
         "label": "Nombre", "required": False, "validation": {"maxLength": 80}},
    ],
}


def _texto(html: str) -> str:
    """Texto visible de un fragmento: sin etiquetas y con espacios normalizados."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _nav(cuerpo: str) -> str:
    m = re.search(r"<nav\b[^>]*\bdata-tt-steps\b[^>]*>(.*?)</nav>", cuerpo, flags=re.S)
    assert m, "no se pinto el indicador de pasos"
    return m.group(1)


def _al_paso_dos(c):
    """POST de avance valido desde 'perfil': aterriza en 'empleo' (paso 2 de 3)."""
    resp = c.post(STEP_URL, data={"tt_step": "0", "tt_next": "1",
                                  "especialidad": "esp3", "carrera": "car2"},
                  follow_redirects=False)
    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-section="empleo"' in resp.text
    return resp.text


# ---------------------------------------------------------------------------
# radio largo -> select
# ---------------------------------------------------------------------------
def test_un_radio_de_veinte_opciones_se_pinta_como_select_con_los_mismos_values(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    m = re.search(r'(<select\b[^>]*\bname="especialidad"[^>]*>)(.*?)</select>', cuerpo, flags=re.S)
    assert m, "el radio de 20 opciones no salio como <select>"
    etiqueta, opciones = m.group(1), m.group(2)
    assert 'aria-labelledby="f-especialidad-lbl"' in etiqueta, etiqueta
    assert 'id="f-especialidad-lbl"' in cuerpo
    assert '<option value="">Selecciona una opción…</option>' in opciones
    valores = re.findall(r'<option value="([^"]*)"', opciones)
    assert valores == [""] + [f"esp{i}" for i in range(1, 21)], valores
    # Ni un solo radio sobrevive con ese nombre: un control a medias mandaria
    # dos valores para la misma llave.
    assert not re.search(r'<input\b[^>]*name="especialidad"', cuerpo)


def test_un_radio_de_diecinueve_opciones_sigue_siendo_radio(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    radios = re.findall(r'<input\b[^>]*type="radio"[^>]*name="carrera"', cuerpo)
    assert len(radios) == 19, len(radios)
    assert not re.search(r'<select\b[^>]*name="carrera"', cuerpo)


def test_el_select_de_un_radio_largo_vuelve_con_la_respuesta_del_borrador(
    client_as, make_student, make_survey_form, db_session,
):
    """`applyValues` y el re-render tienen que encontrar la opcion marcada."""
    from itcj2.apps.titulatec.models import SurveyDraft

    form = make_survey_form(schema=SCHEMA_TRES)
    student = make_student()
    # `carrera` (obligatoria) sigue vacia: `_start_step` aterriza en 'perfil'.
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id,
                               answers={"especialidad": "esp7"}))
    db_session.flush()

    cuerpo = client_as(student).get(SURVEY_URL, follow_redirects=False).text

    assert '<option value="esp7" selected>' in cuerpo
    assert cuerpo.count(" selected>") == 1, "mas de una opcion marcada en la pagina"


def test_el_select_de_un_radio_largo_marca_su_error_en_linea(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    resp = client_as(make_student()).post(
        STEP_URL, data={"tt_step": "0", "tt_next": "1", "carrera": "car1",
                        "especialidad": ""},
        follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    cuerpo = resp.text
    assert 'data-tt-section="perfil"' in cuerpo                 # no avanzo
    assert 'data-tt-error="especialidad"' in cuerpo
    m = re.search(r'<select\b[^>]*\bname="especialidad"[^>]*>', cuerpo)
    assert m and 'aria-invalid="true"' in m.group(0), m and m.group(0)
    assert 'aria-describedby="f-especialidad-err"' in m.group(0), m.group(0)
    assert 'id="f-especialidad-err"' in cuerpo


# ---------------------------------------------------------------------------
# Indicador de pasos: una sola vez, paso actual y barra de progreso
# ---------------------------------------------------------------------------
def test_el_indicador_de_pasos_se_pinta_una_sola_vez(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = _al_paso_dos(client_as(make_student()))

    assert cuerpo.count("data-tt-steps") == 1
    assert cuerpo.count('class="tt-steps-list"') == 1
    assert len(re.findall(r'<li class="tt-steps-item\b', cuerpo)) == 3
    # "Paso N de M" una sola vez: `getByText('Paso 2 de 3')` es estricto.
    assert cuerpo.count("Paso 2 de 3") == 1


def test_el_paso_actual_lleva_aria_current_y_solo_los_visitados_son_botones(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = _al_paso_dos(client_as(make_student()))
    nav = _nav(cuerpo)

    assert cuerpo.count('aria-current="step"') == 1
    items = re.findall(r'<li class="tt-steps-item ([^"]+)">(.*?)</li>', nav, flags=re.S)
    estados = {_texto(html): (estado, html) for estado, html in items}
    assert set(estados) == {"Perfil del egresado", "Empleo actual", "Comentarios finales"}, estados.keys()

    estado, html = estados["Perfil del egresado"]
    assert estado == "is-done"
    assert re.search(r'<button type="submit" name="tt_goto" value="0" class="tt-steps-link"', html), html

    estado, html = estados["Empleo actual"]
    assert estado == "is-current"
    assert 'aria-current="step"' in html
    assert "<button" not in html

    estado, html = estados["Comentarios finales"]
    assert estado == "is-upcoming"
    assert "<button" not in html and "tt-steps-link" not in html


def test_la_barra_de_progreso_refleja_el_paso(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = _al_paso_dos(client_as(make_student()))
    nav = _nav(cuerpo)

    m = re.search(r"<progress\b[^>]*>", nav)
    assert m, "no hay barra de progreso en el indicador"
    barra = m.group(0)
    assert 'value="2"' in barra and 'max="3"' in barra, barra
    ref = re.search(r'aria-labelledby="([^"]+)"', barra)
    assert ref, f"la barra no tiene nombre accesible: {barra!r}"
    assert f'id="{ref.group(1)}"' in nav, "la barra apunta a un id que no existe"


def test_el_formulario_declara_una_vista_constante_para_no_reanimar_el_riel(
    client_as, make_student, make_survey_form,
):
    """`titulatec-utils.js` re-anima el destino de cada swap salvo que su
    `data-tt-view` sea el mismo antes y despues. Sin esto, cada "Siguiente"
    haria rebotar el riel entero (que vive dentro del formulario) aunque no
    haya cambiado nada en el."""
    make_survey_form(schema=SCHEMA_TRES)
    c = client_as(make_student())

    get = c.get(SURVEY_URL, follow_redirects=False).text
    paso = _al_paso_dos(c)

    vistas = [re.search(r'<form\b[^>]*\bid="tt-survey-form"[^>]*>', html).group(0) for html in (get, paso)]
    valores = [re.search(r'data-tt-view="([^"]+)"', v) for v in vistas]
    assert all(valores), vistas
    assert valores[0].group(1) == valores[1].group(1)


# ---------------------------------------------------------------------------
# Opciones como tiles
# ---------------------------------------------------------------------------
def test_las_opciones_son_tiles_con_el_input_nativo_dentro_de_su_label(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_OPCIONES)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    def tiles(tipo, name):
        return re.findall(
            r'<label class="tt-opt\b[^"]*">\s*<input\b[^>]*\btype="%s"[^>]*\bname="%s"' % (tipo, name),
            cuerpo)

    assert len(tiles("radio", "likert")) == 4
    assert len(tiles("radio", "sexo")) == 2
    assert len(tiles("checkbox", "areas")) == 3
    assert len(tiles("radio", "recomienda")) == 2
    assert len(tiles("checkbox", "contacto")) == 1
    # Ningun input de opcion quedo fuera de su tile.
    sueltos = re.findall(r'<div class="form-check">', cuerpo)
    assert sueltos == [], "quedan opciones con el marcado viejo de Bootstrap"
    # La escala: un chip por punto, con el radio nativo dentro.
    chips = re.findall(r'<label class="tt-scale-opt">\s*<input\b[^>]*\bname="relacion" value="(\d)"', cuerpo)
    assert chips == ["1", "2", "3", "4", "5"], chips
    # Los escalares siguen siendo controles a ancho completo.
    assert 'form-select" id="f-turno"' in cuerpo
    assert 'type="text" id="f-nombre"' in cuerpo


def test_la_distribucion_de_opciones_depende_del_numero_y_del_largo_del_rotulo(
    client_as, make_student, make_survey_form,
):
    """Lo decide la plantilla, no el CSS: el CSS no sabe contar opciones ni medir rotulos."""
    make_survey_form(schema=SCHEMA_OPCIONES)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    def layout(key):
        m = re.search(r'data-tt-field="%s".*?class="tt-opts\b([^"]*)"' % key, cuerpo, flags=re.S)
        assert m, "el campo %s no pinta un grupo de opciones" % key
        return set(m.group(1).split())

    assert "tt-opts--row" in layout("likert")        # Likert de 4 cortas: en fila
    assert {"tt-opts--row", "tt-opts--pair"} <= layout("sexo")   # 2 cortas: tambien a 2 en movil
    assert "tt-opts--cols2" in layout("carrera_larga")    # 16 con rotulo largo: 2 columnas
    assert layout("sector") == set()                 # rotulos de ~60 caracteres: una columna
    assert "tt-opts--row" in layout("recomienda")    # Si/No


# ---------------------------------------------------------------------------
# Barra de acciones: nombres accesibles EXACTOS
# ---------------------------------------------------------------------------
def test_los_botones_de_la_barra_conservan_su_nombre_exacto(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)
    c = client_as(make_student())

    primero = c.get(SURVEY_URL, follow_redirects=False).text
    m = re.search(r'<button\b[^>]*name="tt_next"[^>]*>(.*?)</button>', primero, flags=re.S)
    assert m and _texto(m.group(1)) == "Siguiente", m and m.group(1)

    segundo = _al_paso_dos(c)
    m = re.search(r'<button\b[^>]*name="tt_goto"[^>]*class="btn\b[^"]*"[^>]*>(.*?)</button>',
                  segundo, flags=re.S)
    assert m and _texto(m.group(1)) == "Atrás", m and m.group(1)

    ultimo = c.post(STEP_URL, data={"tt_step": "1", "tt_next": "1", "especialidad": "esp3",
                                    "carrera": "car2", "empresa": "ITCJ"},
                    follow_redirects=False).text
    assert 'data-tt-section="cierre"' in ultimo
    textos = [_texto(b) for b in re.findall(r"<button\b[^>]*>(.*?)</button>", ultimo, flags=re.S)]
    assert "Enviar respuestas" in textos, textos
    # Un icono decorativo no puede colarse en el nombre accesible.
    for html in (primero, segundo, ultimo):
        for icono in re.findall(r"<i\b[^>]*>", html):
            assert 'aria-hidden="true"' in icono, icono


# ---------------------------------------------------------------------------
# El layout ancho es SOLO de la encuesta
# ---------------------------------------------------------------------------
def test_la_encuesta_opta_por_el_modificador_ancho_sin_soltar_la_base(
    client_as, make_student, make_survey_form,
):
    make_survey_form(schema=SCHEMA_TRES)

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    main = re.search(r"<main\b[^>]*>", cuerpo, flags=re.S).group(0)
    for clase in ("tt-public-main", "tt-prose", "tt-public-main--survey"):
        assert clase in main, main
    assert 'data-tt-page="public_survey"' in main


def test_la_inscripcion_no_hereda_el_modificador_de_la_encuesta():
    """Fuente, no render: la inscripcion la reescribe otra tarea en paralelo y
    su ruta puede no estar en pie. Lo que se fija es que el ancho nuevo entra
    por un bloque que SOLO llena `survey.html`, y que la regla de 60ch de la
    base sigue intacta."""
    base = re.sub(r"{#.*?#}", " ", (PUBLIC_TPL / "base_public.html").read_text(encoding="utf-8"), flags=re.S)
    main = re.search(r"<main\b[^>]*>", base, flags=re.S).group(0)
    assert "{% block public_main_class %}{% endblock %}" in main, main

    survey = (PUBLIC_TPL / "survey.html").read_text(encoding="utf-8")
    assert re.search(r"{%\s*block public_main_class\s*%}.*tt-public-main--survey", survey, flags=re.S)

    enroll = (PUBLIC_TPL / "enroll.html").read_text(encoding="utf-8")
    assert "public_main_class" not in enroll
    assert "tt-public-main--survey" not in enroll

    css = CSS_PUBLICO.read_text(encoding="utf-8")
    assert re.search(r"\.tt-public-main\.tt-prose\s*\{[^}]*max-width:\s*60ch", css), \
        "el tope de 60ch de la base publica cambio: la inscripcion cambiaria de ancho"


def test_la_hoja_publica_no_usa_mute_para_texto_ni_transition_all():
    """`--tt-mute` da 2.56:1 (titulatec.css lo marca PROHIBIDO PARA TEXTO) y
    `transition: all` anima propiedades de layout (ui_motion.md)."""
    css = re.sub(r"/\*.*?\*/", " ", CSS_PUBLICO.read_text(encoding="utf-8"), flags=re.S)

    assert not re.search(r"(?<![-\w])color\s*:\s*var\(--tt-mute\)", css)
    assert not re.search(r"transition\s*:\s*all\b", css)
