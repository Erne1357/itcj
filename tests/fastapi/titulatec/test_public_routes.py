"""Censo de rutas: que es publico y que no, medido peticion por peticion.

TODA asercion va con `follow_redirects=False`. El `TestClient` sigue redirects
por omision, asi que un 302 al login se convierte en un 200 y la prueba pasaria
por la razon EQUIVOCADA — justo la razon por la que este archivo existe.

Por lo mismo, para las rutas publicas no basta el status: se exige un MARCADOR
del cuerpo (`data-tt-page`, que pone `base_public.html`). Un 200 sin marcador
puede ser cualquier cosa.

Del lado guardado, `require_page_app` lanza `PageLoginRequired` ANTES de tocar
la BD y el handler de `main.py` responde **302 a `/itcj/login`**. Nunca 403: el
403 solo existe para alguien autenticado.

ESTE ARCHIVO SE COMMITEA EN ROJO A PROPOSITO. Las rutas publicas las crean las
tareas de la encuesta publica y de la inscripcion publica; hasta entonces los
siete tests de la primera seccion fallan. Es su puerta de aceptacion. Lo que SI
esta verde desde ya: el censo y el contrato de los artefactos de la base
publica (ultima seccion), que son lo que esta tarea entrega.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import itcj2

# Rutas PUBLICAS (seccion 7.1): sin `Depends(require_page_*)`, sin `dependencies=[]`.
RUTA_ENCUESTA = "/titulatec/encuesta-egresados"
RUTA_INSCRIPCION = "/titulatec/inscripcion"

# Muestra de rutas GUARDADAS ya existentes. Cada una de un router distinto, para
# que el censo no dependa de un solo archivo.
RUTAS_GUARDADAS = [
    "/titulatec/",                       # landing.py
    "/titulatec/admin/",                 # admin.py
    "/titulatec/admin/processes",        # admin.py
    "/titulatec/admin/cohorts",          # admin.py
    "/titulatec/admin/documents",        # documents.py
    "/titulatec/admin/appointments",     # appointments.py
    "/titulatec/admin/officers",         # officers.py
    "/titulatec/student/dashboard",      # student.py
    "/titulatec/student/documents",      # student.py
    "/titulatec/student/cita",           # student.py
]

# Artefactos que ENTREGA esta tarea. Se localizan desde el paquete instalado y
# no desde el cwd: pytest puede correrse desde cualquier directorio.
_APP_DIR = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"
BASE_PUBLICA = _APP_DIR / "templates" / "titulatec" / "public" / "base_public.html"
JS_ERRORES = _APP_DIR / "static" / "js" / "shared" / "tt-errors.js"
CSS_PUBLICO = _APP_DIR / "static" / "css" / "public.css"


def _sin_comentarios(fuente: str) -> str:
    """Quita comentarios de bloque y de linea.

    Sin esto, un test de fuente miente: la cabecera de `tt-errors.js` NOMBRA
    `decodeHeaderMsg` para explicar por que decodifica, asi que un `assert
    "decodeHeaderMsg" in fuente` seguiria pasando aunque alguien borrara la
    llamada y dejara el comentario. El comentario no decodifica nada.
    """
    fuente = re.sub(r"/\*.*?\*/", " ", fuente, flags=re.S)
    fuente = re.sub(r"^\s*//.*$", " ", fuente, flags=re.M)
    return fuente


def _sin_comentarios_jinja(fuente: str) -> str:
    """Quita los bloques `{# ... #}` de una plantilla.

    Misma trampa que en el JS, y esta ya mordio: la cabecera de
    `base_public.html` DOCUMENTA el ancla escribiendo `<main data-tt-page="...">`
    dentro de un comentario, asi que un `re.search(r"<main...")` sobre la fuente
    cruda encuentra el del comentario —que no renderiza nada— y no el de verdad.
    """
    return re.sub(r"{#.*?#}", " ", fuente, flags=re.S)


@pytest.fixture()
def encuesta_publica(db_session, make_survey_form):
    """UNA encuesta `egresados` abierta, dentro de la transaccion del test.

    La BD de dev puede traer ya la v1 sembrada por su seeder, y el indice
    parcial `uq_titulatec_survey_forms_open` (una sola version `open` por
    `code`) rechazaria el insert. Se cierran las abiertas primero y se crea una
    version alta. Bajo la CI de base vacia el UPDATE no toca nada y da igual.
    """
    from itcj2.apps.titulatec.models import SurveyForm

    (db_session.query(SurveyForm)
     .filter(SurveyForm.code == "egresados", SurveyForm.status == "open")
     .update({"status": "closed"}, synchronize_session=False))
    db_session.flush()
    return make_survey_form(code="egresados", version=99, status="open")


@pytest.fixture()
def convocatoria_publica(db_session, make_cohort):
    """EXACTAMENTE una convocatoria abierta dentro de la transaccion del test.

    `CohortService.public_enrollment_cohort` FALLA CERRADO con 503 si encuentra
    mas de una abierta (seccion 6.6), y hasta este spec TODA convocatoria nacia
    con `status='open'` y fechas NULL: la BD de dev trae varias. Sin este
    barrido, el censo pasaria o fallaria segun la maquina.
    """
    from itcj2.apps.titulatec.models import Cohort

    db_session.query(Cohort).update({"status": "draft"}, synchronize_session=False)
    db_session.flush()
    return make_cohort(status="open",
                       opens_at=date.today() - timedelta(days=1),
                       closes_at=date.today() + timedelta(days=30))


# ---------------------------------------------------------------------------
# Rutas publicas: 200 + marcador de cuerpo
# ---------------------------------------------------------------------------
def test_la_encuesta_abre_sin_cookie(client, encuesta_publica):
    client.cookies.clear()                      # vuelta a anonimo, explicita

    resp = client.get(RUTA_ENCUESTA, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    # El marcador prueba que se renderizo LA pagina, no un login seguido.
    assert 'data-tt-page="public_survey"' in resp.text


def test_la_encuesta_anonima_avisa_que_no_cuenta_para_el_expediente(
    client, encuesta_publica,
):
    """Criterio de aceptacion 2: el aviso es persistente y visible SIN sesion."""
    client.cookies.clear()

    resp = client.get(RUTA_ENCUESTA, follow_redirects=False)

    assert resp.status_code == 200
    assert "data-tt-anon-notice" in resp.text


def test_la_inscripcion_abre_sin_cookie(client, convocatoria_publica):
    client.cookies.clear()

    resp = client.get(RUTA_INSCRIPCION, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    assert 'data-tt-page="public_enroll"' in resp.text


def test_la_inscripcion_sin_convocatoria_abierta_sigue_siendo_200(client, db_session):
    """Seccion 6.8: la tarjeta de cierre se pinta en la MISMA base publica."""
    from itcj2.apps.titulatec.models import Cohort

    db_session.query(Cohort).update({"status": "draft"}, synchronize_session=False)
    db_session.flush()
    client.cookies.clear()

    resp = client.get(RUTA_INSCRIPCION, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    assert 'data-tt-page="public_enroll"' in resp.text


def test_las_paginas_publicas_cargan_el_modulo_de_errores_y_no_el_del_alumno(
    client, encuesta_publica,
):
    """`student/errors.js` NO decodifica `X-Tt-Error` y pintaria `n%C3%BAmero`."""
    client.cookies.clear()

    resp = client.get(RUTA_ENCUESTA, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    cuerpo = resp.text
    assert "/static/titulatec/js/shared/tt-errors.js" in cuerpo
    assert "/static/titulatec/js/student/errors.js" not in cuerpo


def test_la_base_publica_no_instancia_el_shell_del_alumno(client, encuesta_publica):
    """Nada de `mobile-app-shell` ni FAB: asumen sesion y romperian el chrome.

    Las dos aserciones de fondo son `not in`, asi que por si solas pasan EN
    VACIO mientras la ruta no exista: lo que hoy se sirve para
    `/titulatec/...` inexistente es `core/errors/core_error.html` (el prefijo
    no esta en `_APP_BY_PREFIX` de `main.py`, asi que cae al de core) y esa
    pagina tampoco trae el shell del alumno. Por eso primero se exige que HAYA
    pagina publica que juzgar: sin el 200 y el marcador, el test no mide nada.
    """
    client.cookies.clear()

    resp = client.get(RUTA_ENCUESTA, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    cuerpo = resp.text
    assert 'data-tt-page="public_survey"' in cuerpo
    assert "mobile-app-shell" not in cuerpo
    assert "app-fab-widget" not in cuerpo


def test_las_paginas_publicas_optan_por_el_tope_de_lectura(client, encuesta_publica):
    """`base.html` pinta `{% block content %}` desnudo: sin tope, 1920 px de linea."""
    client.cookies.clear()

    resp = client.get(RUTA_ENCUESTA, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("location") or resp.text[:300]
    cuerpo = resp.text
    assert "tt-prose" in cuerpo
    assert "/static/titulatec/css/public.css" in cuerpo


# ---------------------------------------------------------------------------
# Censo: todo lo demas sigue cerrado, y cerrado de la misma forma
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ruta", RUTAS_GUARDADAS)
def test_censo_toda_ruta_guardada_redirige_al_login_exactamente(client, ruta):
    """302 a `/itcj/login`. Ni 200, ni 403, ni 404, ni otro destino."""
    client.cookies.clear()

    resp = client.get(ruta, follow_redirects=False)

    assert resp.status_code == 302, (
        f"{ruta} devolvio {resp.status_code} a un anonimo. `require_page_app` "
        f"levanta PageLoginRequired antes que cualquier PageForbidden, y el "
        f"handler de main.py responde 302."
    )
    assert resp.headers["location"] == "/itcj/login", (
        f"{ruta} redirige a {resp.headers.get('location')!r} en vez de /itcj/login."
    )


def test_censo_una_ruta_publica_no_esta_en_la_lista_de_guardadas():
    """Guarda contra el copy-paste: si alguien mete una publica ahi, el censo mentiria."""
    assert RUTA_ENCUESTA not in RUTAS_GUARDADAS
    assert RUTA_INSCRIPCION not in RUTAS_GUARDADAS


# ---------------------------------------------------------------------------
# Contrato de los artefactos de la base publica
# ---------------------------------------------------------------------------
# Los siete tests de arriba son la puerta de aceptacion de las paginas publicas
# y estan en rojo hasta que existan. Estos miden la FUENTE de lo que esta tarea
# si entrega, y por eso protegen hoy —no dentro de ocho tareas— las tres
# decisiones que hacen util a esta base: de quien hereda, que decodifica y como
# se esconde el honeypot.
def test_la_base_publica_extiende_la_base_raiz_y_no_la_del_alumno():
    """`base_student.html` instancia el shell movil, el FAB y el drawer de perfil.

    Los tres leen sesion. Heredar de ahi le renderiza a un anonimo un chrome
    roto (nombre 'Alumno' inventado, boton de cerrar sesion que no tiene que
    cerrar, FAB que pide notificaciones sin token).
    """
    fuente = _sin_comentarios_jinja(BASE_PUBLICA.read_text(encoding="utf-8"))

    m = re.search(r"{%\s*extends\s+[\"']([^\"']+)[\"']\s*%}", fuente)
    assert m, "base_public.html no declara de quien hereda."
    assert m.group(1) == "titulatec/base.html", (
        f"base_public.html hereda de {m.group(1)!r}. Debe heredar de "
        f"'titulatec/base.html' DIRECTAMENTE."
    )


def test_la_base_publica_ancla_la_vista_y_topa_el_ancho_de_lectura():
    """El <main> es a la vez el ancla de los E2E y la columna de lectura.

    `base.html` pinta `{% block content %}` desnudo dentro de <body>, y el tope
    del alumno (`.tt-stu .tt-canvas-inner p`) esta atado a una clase que solo
    pone su base. Sin optar por `.tt-prose` aqui, a 1920 px una pregunta sale
    con lineas de ~200 caracteres.
    """
    fuente = _sin_comentarios_jinja(BASE_PUBLICA.read_text(encoding="utf-8"))

    m = re.search(r"<main\b[^>]*>", fuente, flags=re.S)
    assert m, "base_public.html no tiene <main>."
    main = m.group(0)
    assert "tt-prose" in main, f"El <main> no opta por el tope de lectura: {main!r}"
    assert "data-tt-page=" in main, f"El <main> no expone el ancla estable: {main!r}"
    assert "css/public.css" in fuente, "La base no carga su propia hoja."


def test_la_base_publica_carga_el_modulo_de_errores_publico():
    """El escucha de HTMX se carga desde LA BASE, no desde cada pagina.

    Es la misma leccion que dejo `formato_b.html` en el lado del alumno: si cada
    vista trae el suyo, alguna se queda sin el y el visitante pulsa "Enviar" sin
    que ocurra nada visible (htmx no swappea en un 4xx). Y tiene que ser
    `shared/tt-errors.js`, no `student/errors.js`: aquel decodifica la cabecera
    y este la pinta cruda.

    El equivalente RENDERIZADO de este test vive arriba y esta en rojo hasta que
    exista una pagina publica; este mide la fuente y por eso protege la base
    desde hoy.
    """
    fuente = _sin_comentarios_jinja(BASE_PUBLICA.read_text(encoding="utf-8"))

    assert "js/shared/tt-errors.js" in fuente, (
        "base_public.html no carga el modulo de errores: cualquier 4xx dejaria "
        "el boton mudo en TODA pagina publica."
    )
    assert "js/student/errors.js" not in fuente, (
        "base_public.html carga el modulo del ALUMNO, que pinta X-Tt-Error "
        "cruda: un mensaje con acentos se veria como 'n%C3%BAmero'."
    )


def test_la_base_publica_declara_morph_fuera_de_lo_que_se_swappea():
    """`hx-ext="morph"` vive en el contenedor exterior, que nunca entra al swap.

    Si viviera en el nodo que se reemplaza, la respuesta no traeria el atributo
    y htmx caeria EN SILENCIO a `innerHTML`, anidando el destino dentro de si
    mismo en cada navegacion (el mismo fallo que documenta
    `admin/base_admin.html:22-28`). Es silencioso: nada revienta, la pagina solo
    se va llenando de copias anidadas.
    """
    fuente = _sin_comentarios_jinja(BASE_PUBLICA.read_text(encoding="utf-8"))

    m = re.search(r"<div\b[^>]*\btt-public-shell\b[^>]*>", fuente, flags=re.S)
    assert m, "base_public.html no tiene el contenedor exterior .tt-public-shell."
    assert 'hx-ext="morph"' in m.group(0), (
        f"El contenedor exterior no declara morph: {m.group(0)!r}"
    )
    # Y NO en el <main>, que si es candidato a ser el destino de un swap.
    main = re.search(r"<main\b[^>]*>", fuente, flags=re.S)
    assert main and "hx-ext" not in main.group(0), (
        "El <main> declara la extension; ahi se pierde al primer morph."
    )


def test_el_modulo_de_errores_publico_decodifica_la_cabecera():
    """Sin `decodeHeaderMsg` el visitante lee `n%C3%BAmero` en pantalla.

    Es la unica diferencia de fondo con `student/errors.js`, que pinta
    `X-Tt-Error` crudo. Los headers HTTP son latin-1, asi que las rutas
    publicas percent-codifican el mensaje al escribirlo.
    """
    codigo = _sin_comentarios(JS_ERRORES.read_text(encoding="utf-8"))

    assert "htmx:responseError" in codigo, "No registra el escucha de errores 4xx."
    assert "X-Tt-Error" in codigo, "No lee la cabecera del mensaje."
    assert "decodeHeaderMsg" in codigo, (
        "El modulo publico pinta la cabecera CRUDA. Un mensaje con acentos "
        "—o sea, todos— llegaria a pantalla como 'n%C3%BAmero'."
    )


def test_el_modulo_de_errores_publico_cubre_el_fallo_de_red():
    """Un fallo de red no llega como `responseError`: sin esto el boton queda mudo."""
    codigo = _sin_comentarios(JS_ERRORES.read_text(encoding="utf-8"))

    assert "htmx:sendError" in codigo
    # Y se registra en `document`, que nunca entra a un swap de htmx.
    assert "document.addEventListener" in codigo


def test_el_honeypot_publico_se_esconde_fuera_de_pantalla_no_con_display_none():
    """El E2E de la trampa lo mide con `boundingBox()`, no con `toBeHidden()`.

    Para Playwright una caja de 1x1 en `left:-9999px` sigue siendo VISIBLE, y
    esa es justo la propiedad que se mide. Cambiarlo por `display:none` (o por
    el atributo `hidden`) rompe esa spec y ademas anula la trampa: un bot salta
    antes un campo `display:none` que uno posicionado fuera de pantalla.
    """
    css = CSS_PUBLICO.read_text(encoding="utf-8")

    m = re.search(r"\.tt-public-hp\s*\{([^}]*)\}", css)
    assert m, "public.css no define el honeypot .tt-public-hp."
    bloque = m.group(1)
    assert "-9999px" in bloque, f"El honeypot no se saca de pantalla: {bloque!r}"
    assert "display" not in bloque, (
        f"El honeypot usa `display`, que lo saca del arbol y rompe el E2E: {bloque!r}"
    )
