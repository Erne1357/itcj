"""Guardas estructurales (AST, sin BD) del perfil de titulación posgrado.

Spec `docs/superpowers/specs/2026-09-30-titulatec-posgrado-design.md` §6
(invariantes) y §4 (diseño). Las Tareas 3-6 de ese plan retiraron las copias
literales que había regadas por `pages/` y `services/survey_service.py` --
cada una vivía DUPLICADA porque nadie tenía un único lugar al que preguntar
"¿qué documentos lleva la fase 1 de este proceso?" / "¿qué formulario de
encuesta le toca?" / "¿es esta carrera de posgrado?". Estos tres censos NO
prueban comportamiento (eso ya lo hacen `test_document_service.py`,
`test_survey_form_by_track.py`, `test_track_service.py` y compañía): prueban
que la copia no VUELVE a aparecer en otro archivo, algo que ningún test de
comportamiento puede detectar porque una copia nueva puede funcionar
perfectamente bien... hasta que diverge de la original.

Por qué AST y no `"texto" in fuente`
-------------------------------------
Un grep de texto no distingue un literal real (`("birth_certificate", ...)`)
de una mención en un comentario o un docstring -- de hecho
`models/document_type.py` documenta el código en un comentario a propósito, y
un grep ingenuo lo marcaría. `ast.parse` ve la ESTRUCTURA: una lista/tupla/set
que de verdad contiene la constante, una llamada que de verdad recibe el
argumento, una comparación que de verdad opera sobre el atributo. Es el mismo
instrumento que ya usan `test_scope_guard.py` y `test_permissions_contract.py`
sobre este mismo paquete.

Cada censo trae su propio "el detector ve lo que tiene que ver"
(`test_el_detector_de_*`): un censo que nunca deja de estar en verde porque
el patrón que busca ya no existe en ningún lado es indistinguible de un censo
roto que no detecta nada. Mismo espíritu que
`test_mail_writers.py::test_el_detector_ve_lo_que_tiene_que_ver`.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TITULATEC_DIR = REPO_ROOT / "itcj2" / "apps" / "titulatec"
PAGES_DIR = TITULATEC_DIR / "pages"

DOCUMENT_SERVICE = TITULATEC_DIR / "services" / "document_service.py"
TRACK_SERVICE = TITULATEC_DIR / "services" / "track_service.py"

# Excepción documentada y revisada (NO una copia superviviente): la bandeja
# Encuestas (`pages/surveys_admin.py::_resolve_form`) es un LISTADO admin que
# muestra TODOS los formularios y necesita un default de "qué mostrar si
# nadie eligió uno" -- a propósito el de licenciatura, para no sorprender a
# quien entra sin tocar el selector apenas exista una versión abierta de
# `egresados_posgrado` (spec §4.5; Tarea 6, `task-6-report.md` self-review:
# "solo quedan las referencias intencionales ... y el `open_form(db,
# SURVEY_CODE)` explícito en `surveys_admin._resolve_form`"). Es un default
# de PANTALLA, no la resolución "qué formulario le toca a ESTE egresado" que
# exige el invariante 5 -- esa vive en `SurveyService.form_for_user` y es lo
# que usan las 4 rutas públicas, con CERO referencias residuales confirmadas
# en el mismo self-review. Por eso el censo de abajo excluye este único
# archivo en vez de fallar en rojo para siempre contra código ya revisado.
SURVEYS_ADMIN_INTENTIONAL_DEFAULT = PAGES_DIR / "surveys_admin.py"


def _py_files(root: Path) -> list[Path]:
    """Todos los `.py` bajo `root`, recursivo, orden estable."""
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _called_name(func: ast.expr) -> str:
    """Nombre del callable de un `Call`: `f(...)` -> "f"; `modulo.f(...)` -> "f"."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


# ---------------------------------------------------------------------------
# Guardia 1 -- lista única de documentos iniciales (invariante 1)
# ---------------------------------------------------------------------------
def _birth_certificate_literal_lines(tree: ast.Module) -> list[int]:
    """Líneas de `ast.List`/`ast.Tuple`/`ast.Set` que CONTIENEN la constante
    string `"birth_certificate"` como uno de sus elementos.

    Las llaves de un `dict` (p. ej. `utils/storage.py::_DOCUMENT_LABELS`) no
    son `List`/`Tuple`/`Set` -- un `ast.Dict` es un tipo de nodo distinto, así
    que quedan fuera sin necesidad de un caso especial.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        if any(isinstance(e, ast.Constant) and e.value == "birth_certificate"
               for e in node.elts):
            out.append(node.lineno)
    return out


def test_ninguna_lista_de_birth_certificate_fuera_de_document_service():
    """`DocumentService.BASE_INITIAL_DOCS` es la ÚNICA fuente del set base.

    Antes de las Tareas 3-5, `("birth_certificate", "high_school_cert",
    "curp")` estaba copiado tal cual en `pages/documents.py`,
    `pages/student.py`, `pages/appointments.py` y `pages/admin.py` -- ninguno
    sabía que existían el resto, y un perfil de posgrado con 7 documentos
    hubiera exigido tocar los cinco lugares a la vez. Si esta copia
    reaparece en cualquiera de ellos (o en uno nuevo), este censo la
    detecta aunque el código copiado "funcione" -- el problema no es que
    falle hoy, es que no hay forma de que las cinco copias se mantengan
    iguales mañana.
    """
    ofensas = []
    for path in _py_files(TITULATEC_DIR):
        if path == DOCUMENT_SERVICE:
            continue
        tree = _parse(path)
        for lineno in _birth_certificate_literal_lines(tree):
            ofensas.append(f"{_rel(path)}:{lineno}")

    assert not ofensas, (
        "Copia de la lista de documentos iniciales fuera de "
        "services/document_service.py (usa DocumentService.BASE_INITIAL_DOCS / "
        "initial_doc_types_for en su lugar):\n" + "\n".join(ofensas)
    )


_MUESTRA_BIRTH_CERTIFICATE = '''
# El código en un COMENTARIO no cuenta: 'birth_certificate' no es un nodo AST.
BASE = ("birth_certificate", "high_school_cert", "curp")          # el original
COPIA = ["birth_certificate", "high_school_cert", "curp"]         # SI cuenta
SET_COPIA = {"birth_certificate", "curp"}                          # SI cuenta
OTRA_COSA = ("birth_certificates", "efirma")                       # plural: NO cuenta
ETIQUETAS = {"birth_certificate": "ACTA"}                          # llave de dict: NO cuenta
'''


def test_el_detector_de_birth_certificate_ve_lo_que_tiene_que_ver():
    """Autoprueba del censo: sin esto, un detector roto (que nunca marca nada)
    y uno correcto se verían idénticos -- los dos dejarían la prueba de
    arriba en verde."""
    lineas = _birth_certificate_literal_lines(ast.parse(_MUESTRA_BIRTH_CERTIFICATE))
    # BASE (tupla, línea 3) y COPIA (lista, línea 4) y SET_COPIA (set, línea 5).
    assert lineas == [3, 4, 5]


# ---------------------------------------------------------------------------
# Guardia 2 -- formulario de encuesta resuelto por perfil (invariante 5)
# ---------------------------------------------------------------------------
def _open_form_survey_code_lines(tree: ast.Module) -> list[int]:
    """Líneas de una llamada a `open_form(...)` que recibe el NOMBRE
    `SURVEY_CODE` como argumento (posicional o de palabra clave).

    `SurveyService.open_form(db, SURVEY_CODE_POSGRADO)` -- el propio
    `form_for_user` prueba cada código de `SURVEY_CODES_BY_TRACK` en orden,
    `SURVEY_CODE` incluido para la cadena de licenciatura -- NO cuenta: el
    nombre distinto (`SURVEY_CODE_POSGRADO`) no es `SURVEY_CODE`. Lo que este
    censo prohíbe es la firma VIEJA, fija, que ignoraba el perfil por
    completo.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node.func) != "open_form":
            continue
        argumentos = list(node.args) + [kw.value for kw in node.keywords]
        if any(isinstance(a, ast.Name) and a.id == "SURVEY_CODE" for a in argumentos):
            out.append(node.lineno)
    return out


def test_ningun_open_form_con_survey_code_fuera_del_default_de_encuestas():
    """Las 4 rutas públicas resuelven el formulario con `form_for_user`, por
    REQUEST, nunca con la constante fija de licenciatura.

    Antes de la Tarea 6, `GET/POST /titulatec/encuesta-egresados` (y sus
    hermanas de paso/borrador/envío) llamaban `SurveyService.open_form(db,
    SURVEY_CODE)` a secas: un egresado de posgrado siempre habría contestado
    la de licenciatura, incluso el día que exista `egresados_posgrado`. Si
    esa firma reaparece en cualquier archivo de `pages/` que NO sea el
    default deliberado de la bandeja Encuestas (ver
    `SURVEYS_ADMIN_INTENTIONAL_DEFAULT` arriba), este censo lo marca.
    """
    ofensas = []
    for path in sorted(PAGES_DIR.glob("*.py")):
        if path == SURVEYS_ADMIN_INTENTIONAL_DEFAULT:
            continue
        tree = _parse(path)
        for lineno in _open_form_survey_code_lines(tree):
            ofensas.append(f"{_rel(path)}:{lineno}")

    assert not ofensas, (
        "open_form(..., SURVEY_CODE) fuera del default deliberado de "
        "surveys_admin.py (usa SurveyService.form_for_user(db, user_id) en su "
        "lugar):\n" + "\n".join(ofensas)
    )


_MUESTRA_OPEN_FORM = '''
def ruta_vieja(db, user):
    form = SurveyService.open_form(db, SURVEY_CODE)              # SI cuenta
    return form

def ruta_por_kw(db):
    return SurveyService.open_form(db, code=SURVEY_CODE)         # SI cuenta (kwarg)

def ruta_nueva(db, user_id):
    form = SurveyService.form_for_user(db, user_id)              # NO cuenta
    return form

def ruta_posgrado_directo(db):
    return SurveyService.open_form(db, SURVEY_CODE_POSGRADO)     # NO cuenta (otro nombre)
'''


def test_el_detector_de_open_form_ve_lo_que_tiene_que_ver():
    lineas = _open_form_survey_code_lines(ast.parse(_MUESTRA_OPEN_FORM))
    assert lineas == [3, 7]


# ---------------------------------------------------------------------------
# Guardia 3 -- el perfil sale SOLO de TrackService (invariante 2)
# ---------------------------------------------------------------------------
def _level_attribute_compare_lines(tree: ast.Module) -> list[int]:
    """Líneas de un `ast.Compare` donde alguno de los operandos es un
    atributo `.level` (de `Program` o de lo que sea -- por nombre, no por
    tipo: el AST no sabe de clases).

    Deliberadamente angosto (pista del brief de la Tarea 8): LEER
    `program.level` para pasárselo a `TrackService.for_level(...)` está bien
    y es justo lo que hacen hoy `pages/admin.py`, `pages/appointments.py` y
    `pages/documents.py` -- eso es un `ast.IfExp` (`program.level if program
    else None`) o un `ast.Attribute` suelto, nunca un `ast.Compare`. Lo que
    el invariante 2 prohíbe es decidir el perfil COMPARANDO `.level` uno
    mismo (`if program.level == "maestria"`, `level in (...)`) en vez de
    preguntarle a `TrackService`.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operandos = [node.left, *node.comparators]
        if any(isinstance(o, ast.Attribute) and o.attr == "level" for o in operandos):
            out.append(node.lineno)
    return out


def test_ninguna_comparacion_con_program_level_fuera_de_track_service():
    """`TrackService.for_level` es el ÚNICO lugar que traduce `Program.level`
    a perfil (`licenciatura` | `posgrado`).

    Nadie más debe comparar `.level` -- ni con `==`, ni con `in` -- porque
    cada comparación propia es una segunda definición de "qué es posgrado"
    que puede desincronizarse del dominio real
    (`POSTGRADUATE_LEVELS = ("maestria", "doctorado")`) en cuanto ese
    dominio cambie.
    """
    ofensas = []
    for path in _py_files(TITULATEC_DIR):
        if path == TRACK_SERVICE:
            continue
        tree = _parse(path)
        for lineno in _level_attribute_compare_lines(tree):
            ofensas.append(f"{_rel(path)}:{lineno}")

    assert not ofensas, (
        "Comparación con `.level` fuera de services/track_service.py (usa "
        "TrackService.for_level/for_process/for_processes en su lugar):\n"
        + "\n".join(ofensas)
    )


_MUESTRA_LEVEL_COMPARE = '''
def comparacion_directa(program):
    if program.level == "maestria":                    # SI cuenta (Compare, Attribute)
        return "posgrado"
    return "licenciatura"

def membresia(program):
    return program.level in ("maestria", "doctorado")  # SI cuenta (Compare, Attribute)

def lectura_para_track_service(db, program):
    # Igual que pages/admin.py, pages/appointments.py, pages/documents.py:
    # leer el atributo para pasarlo a TrackService no es una comparacion.
    track = TrackService.for_level(program.level if program else None)  # NO cuenta (IfExp)
    return track

def otro_atributo(doc):
    return doc.review_status == "approved"              # NO cuenta (otro atributo)
'''


def test_el_detector_de_level_ve_lo_que_tiene_que_ver():
    lineas = _level_attribute_compare_lines(ast.parse(_MUESTRA_LEVEL_COMPARE))
    assert lineas == [3, 8]
