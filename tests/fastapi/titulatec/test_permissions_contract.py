"""Contrato: todo permiso que el CODIGO exige debe existir en el DML.

Por que existe este test
------------------------
En titulatec la autorizacion es 100% `require_page_app("titulatec", perms=[...])`
y **no hay bypass de admin global** (`itcj2/dependencies.py:104-139`): el gate
resuelve el codigo contra `core_permissions`. Si una ruta exige un codigo que
ningun seeder inserta, la pagina devuelve 403 para TODO el mundo, sin error en
logs y sin forma de arreglarlo desde la UI. Es un fallo silencioso y permanente.

Este es el test que habria atajado el incidente de los seeders borrados: los
permisos viven en `database/DML/` (gitignored, §3 del CLAUDE.md raiz), asi que
nada mas los ata al codigo salvo la disciplina de quien edita.

Como se extrae cada lado
------------------------
- **Codigo**: AST de `itcj2/apps/titulatec/pages/*.py`. Se leen los `perms=` de
  cada `require_page_app(...)`, resolviendo las constantes de modulo
  (`_COHORT_PERMS`, `_VIEW_PERMS`, ...) por nombre; mas los codigos del menu
  `_ADMIN_NAV` (`pages/nav.py:95-103`), donde un codigo inexistente no da 403:
  esconde la pestana para siempre, que es peor.
  Se usa AST y no regex para no confundir codigos de permiso con los `name=`
  de las rutas, que tienen la misma forma (`titulatec.pages.admin.home`).
- **DML**: los `('codigo', ...)` de los `INSERT INTO core_permissions` de
  `database/DML/titulatec/**/*.sql` (02 los declara todos; 07 anade
  `cohort.api.cotejo_reqs`; 08 anade los tres de `review_window.*`; el delta
  `survey_2026_09/09_insert_survey_perms.sql` anade los once de la campana de
  encuesta de egresados: ocho de encuesta/solicitudes mas tres de la
  liberacion de GTV agregados el 2026-09-15). `_declared_by_dml()` usa
  `DML_DIR.rglob("*.sql")`,
  no `glob("*.sql")`, precisamente para alcanzar los archivos dentro de
  subcarpetas de delta como `survey_2026_09/` — es el patron establecido para
  no tocar `03_insert_role_permissions.sql` (sus DELETE se re-aplican en cada
  corrida y revocarian cualquier permiso agregado ahi). Si alguien "simplifica"
  el `rglob` de vuelta a `glob`, los codigos de cualquier delta futuro en su
  propia subcarpeta se vuelven invisibles para este contrato sin que nadie lo
  note: NO LO HAGAS.

`database/` esta gitignored a proposito y NUNCA llega al checkout de CI: si no
esta, el test hace SKIP con motivo, no falla.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PAGES_DIR = REPO_ROOT / "itcj2" / "apps" / "titulatec" / "pages"
DML_DIR = REPO_ROOT / "database" / "DML" / "titulatec"

# Codigo de permiso: 'titulatec.' + al menos dos segmentos mas.
PERM_RE = re.compile(r"^titulatec\.[a-z0-9_]+\.[a-z0-9_.]+$")

# Los 11 codigos del delta de 2026-09 (encuesta de egresados + convocatoria
# abierta + liberacion de GTV, esta ultima agregada el 2026-09-15). Viven en
# database/DML/titulatec/survey_2026_09/, NO en el 02/03.
NUEVOS_2026_09 = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.survey.api.manage",
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.requirement.mark",
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
)


def _module_string_lists(tree: ast.Module) -> dict[str, list[str]]:
    """Constantes de modulo que son listas/tuplas/sets de strings.

    Es lo que permite resolver `perms=_COHORT_PERMS` sin importar el modulo
    (importarlo arrastraria la app entera y sus efectos de import).
    """
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            continue
        values = [e.value for e in node.value.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if values:
            out[target.id] = values
    return out


def _codes_from_perms_arg(node: ast.AST, consts: dict[str, list[str]]) -> list[str]:
    """Resuelve el valor pasado a `perms=`: literal, constante por nombre, o suma."""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if isinstance(node, ast.Name):
        return list(consts.get(node.id, []))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_codes_from_perms_arg(node.left, consts)
                + _codes_from_perms_arg(node.right, consts))
    return []


def _required_by_code() -> dict[str, set[str]]:
    """{codigo de permiso -> {'archivo:linea', ...}} exigidos por pages/."""
    required: dict[str, set[str]] = {}

    def _add(code: str, where: str) -> None:
        if PERM_RE.match(code):
            required.setdefault(code, set()).add(where)

    for path in sorted(PAGES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        consts = _module_string_lists(tree)

        # 1) perms= de cada require_page_app(...)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "require_page_app":
                continue
            for kw in node.keywords:
                if kw.arg == "perms":
                    for code in _codes_from_perms_arg(kw.value, consts):
                        _add(code, f"{path.name}:{node.lineno}")

        # 2) permisos del menu admin (_ADMIN_NAV): un codigo inexistente aqui
        #    no da 403, esconde la pestana en silencio.
        for node in tree.body:
            if not (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "_ADMIN_NAV"):
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    _add(sub.value, f"{path.name}:_ADMIN_NAV")

    return required


def _declared_by_dml() -> dict[str, str]:
    """{codigo -> archivo.sql} declarado en los INSERT INTO core_permissions."""
    declared: dict[str, str] = {}
    insert_re = re.compile(r"INSERT\s+INTO\s+core_permissions", re.IGNORECASE)
    # Filas de la forma: (v_app_id, 'titulatec.x.y.z', 'Nombre', 'Desc')
    row_re = re.compile(r"\(\s*v_app_id\s*,\s*'([^']+)'")

    for path in sorted(DML_DIR.rglob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        if not insert_re.search(sql):
            continue
        for code in row_re.findall(sql):
            if PERM_RE.match(code):
                declared.setdefault(code, path.name)
    return declared


requires_dml = pytest.mark.skipif(
    not DML_DIR.is_dir(),
    reason=(
        "database/DML/titulatec/ no esta en el checkout (gitignored a proposito: "
        "trae PII real y nunca llega a CI). Este contrato solo se puede verificar "
        "en un entorno con los seeders presentes."
    ),
)


def test_el_extractor_ast_encuentra_permisos():
    """Guarda del propio test: si el extractor deja de ver codigos, el contrato
    pasaria vacio y en verde sin verificar nada."""
    required = _required_by_code()

    assert len(required) >= 20, f"el extractor solo vio {len(required)} codigos"
    # Anclas: un permiso de pagina, uno de accion y uno del menu admin.
    assert "titulatec.document.page.list" in required
    assert "titulatec.process.api.approve_phase" in required
    assert "titulatec.ceremony.page.list" in required   # solo vive en _ADMIN_NAV


@requires_dml
def test_todo_permiso_exigido_por_pages_existe_en_el_dml():
    """Si esto se cae, la ruta senalada devuelve 403 permanente en produccion."""
    required = _required_by_code()
    declared = set(_declared_by_dml())

    faltantes = {code: sorted(where) for code, where in required.items()
                 if code not in declared}

    assert not faltantes, (
        "Permisos exigidos por el codigo que NINGUN seeder inserta -> 403 "
        "permanente. Para esta campana van en su propio delta: agregalos a "
        "database/DML/titulatec/survey_2026_09/09_insert_survey_perms.sql "
        "y asignalos en survey_2026_09/10_insert_survey_role_permissions.sql "
        f"(NUNCA en 03_insert_role_permissions.sql, ver docstring del modulo):\n{faltantes}"
    )


@requires_dml
def test_el_dml_declara_los_82_permisos_conocidos():
    """Guarda del OTRO lado: detecta un seeder truncado o borrado.

    82 es el numero verificado en BD tras `titulatec init-titulatec`. Eran 80
    hasta el 2026-09-16, cuando el auto-agendado de citas de cotejo anadio dos
    codigos nuevos (`titulatec.appointment.api.book.own` y
    `titulatec.appointment.api.cancel.own`) al bloque de citas de
    `02_insert_permissions.sql`. Antes de eso eran 77 hasta el 2026-09-15,
    cuando la liberacion de la encuesta de egresados por Gestion Tecnologica y
    Vinculacion (GTV) anadio tres codigos `titulatec.survey_review.*` en el
    mismo delta `survey_2026_09/09_insert_survey_perms.sql`. Antes de eso eran
    69 hasta el 2026-09-07, cuando esa misma campana anadio los ocho de
    encuesta/solicitudes (aparte del 03, que lleva DELETE que se re-aplican en
    cada corrida). Antes de eso eran 66 hasta el 2026-09-03, cuando el
    rediseno de Citas anadio los tres de `review_window.*` en su propio
    archivo 08.

    Si baja, alguien recorto un seeder; si sube, este numero se actualiza junto
    con la doc.
    """
    declared = _declared_by_dml()

    assert len(declared) == 82, (
        f"el DML declara {len(declared)} permisos titulatec, se esperaban 82. "
        "Actualiza este numero SOLO si el cambio en database/DML/titulatec/ es "
        f"intencional. Declarados: {sorted(declared)}"
    )


@requires_dml
def test_los_permisos_de_espacios_estan_en_su_propio_archivo():
    """No pueden vivir en el 03.

    `03_insert_role_permissions.sql` lleva DELETE que se re-aplican en CADA
    corrida de `init-titulatec`. Un permiso concedido ahi puede quedar revocado
    por una re-siembra, y el sintoma es un 403 que aparece solo despues de
    sembrar.
    """
    ocho = (DML_DIR / "08_insert_review_window_perms.sql")
    assert ocho.exists(), "falta 08_insert_review_window_perms.sql"
    cuerpo = ocho.read_text(encoding="utf-8")
    for codigo in ("titulatec.review_window.page.manage",
                   "titulatec.review_window.api.manage",
                   "titulatec.review_window.api.manage.all"):
        assert codigo in cuerpo, f"{codigo} no esta en el archivo 08"

    tres = (DML_DIR / "03_insert_role_permissions.sql").read_text(encoding="utf-8")
    assert "review_window" not in tres, (
        "los permisos de espacios NO pueden vivir en el 03: sus DELETE se "
        "re-aplican en cada corrida y pueden revocarlos")


@requires_dml
def test_el_delta_de_encuesta_e_inscripcion_vive_en_su_subcarpeta():
    """Los 8 permisos de 2026-09 van en survey_2026_09/, nunca en el 03.

    `03_insert_role_permissions.sql` lleva DELETE (cuatro desde el 2026-09-15)
    que se re-aplican en CADA corrida de `titulatec init-titulatec`. Un permiso
    concedido ahi puede quedar revocado por una re-siembra, y el sintoma es un
    403 que aparece solo despues de sembrar. Es la misma regla que ya vigila
    `test_los_permisos_de_espacios_estan_en_su_propio_archivo` para el 08.
    """
    delta = DML_DIR / "survey_2026_09"
    assert delta.is_dir(), (
        "falta database/DML/titulatec/survey_2026_09/. `database/` esta "
        "gitignored: recuperala del respaldo o crea el delta."
    )

    nueve = delta / "09_insert_survey_perms.sql"
    assert nueve.exists(), "falta 09_insert_survey_perms.sql"
    cuerpo = nueve.read_text(encoding="utf-8")
    for codigo in NUEVOS_2026_09:
        assert codigo in cuerpo, f"{codigo} no esta en 09_insert_survey_perms.sql"

    diez = delta / "10_insert_survey_role_permissions.sql"
    assert diez.exists(), "falta 10_insert_survey_role_permissions.sql"
    grants = diez.read_text(encoding="utf-8")
    assert "titulatec_school_services_head" in grants, (
        "el 10 no concede nada a la jefatura de Servicios Escolares")
    assert "titulatec_school_services'" in grants, (
        "titulatec.process.api.requirement.mark tambien va al rol OPERATIVO "
        "(spec 5.4): el encargado es quien usa el checklist de cotejo")

    # El 13 siembra el checklist de cotejo en las convocatorias anteriores al
    # 2026-09-08. Sin el, la guarda de la fase 2 nunca dispara en ninguna de
    # ellas (B3): `missing_required` devuelve `[]` con cero requisitos.
    # `tests/fastapi/titulatec/test_cli_survey_delta.py` fija ademas que algun
    # comando lo corra.
    for nombre in ("11_seed_survey_form.sql", "12_seed_cotejo_codes.sql",
                   "13_seed_cotejo_reqs_all_cohorts.sql"):
        assert (delta / nombre).exists(), f"falta {nombre}"

    tres = (DML_DIR / "03_insert_role_permissions.sql").read_text(encoding="utf-8")
    for codigo in NUEVOS_2026_09:
        assert codigo not in tres, (
            f"{codigo} no puede vivir en el 03: sus DELETE se re-aplican en "
            "cada corrida de init-titulatec y pueden revocarlo")


def _like_to_regex(patron_like: str) -> re.Pattern:
    """Traduce un patron SQL LIKE (solo `%` y `_`) a una regex anclada.

    Caracter por caracter y no `re.escape(...).replace(r"\\%", ...)`: desde
    Python 3.7 `re.escape` YA NO escapa `%` ni `_` (no son especiales para
    regex), asi que ese `.replace` nunca encuentra nada que reemplazar y el
    patron resultante busca un '%' literal en vez de traducirlo a `.*`.
    """
    partes = []
    for ch in patron_like:
        if ch == "%":
            partes.append(".*")
        elif ch == "_":
            partes.append(".")
        else:
            partes.append(re.escape(ch))
    return re.compile("^" + "".join(partes) + "$")


def _grants_de_rol_in(sql: str, rol: str) -> set[str]:
    """Codigos de un `WHERE r.name = '<rol>' AND p.code IN (...)`.

    Es el estilo de `survey_2026_09/10_insert_survey_role_permissions.sql`
    (usa `p.code IN (...)`, no `ARRAY[...]` como el 03 — por eso no se
    reutiliza `_grants_de_rol`).
    """
    patron = (r"WHERE\s+r\.name\s*=\s*'" + re.escape(rol)
              + r"'\s+AND\s+p\.code\s+IN\s*\(([^)]*)\)")
    return {c for bloque in re.findall(patron, sql)
            for c in re.findall(r"'([^']+)'", bloque)}


@requires_dml
def test_el_reparto_de_gtv_libera_encuesta_y_recorta_a_la_jefatura():
    """Spec 2026-09-15-titulatec-liberacion-gtv, seccion 7.

    GTV (`titulatec_tech_management`, rol nuevo) recibe los 3
    `survey_review.*` nuevos mas los 4 `survey.*` y los 2 `notifications.*`
    (9 en total: "Verificacion en BD... con 9 permisos en titulatec"). La
    jefatura de Servicios Escolares (`titulatec_school_services_head`) pierde
    `survey.*` -pasa a GTV, spec D12- pero conserva sus otros 4:
    `enrollment_request.*` y `requirement.mark`.
    """
    diez = (DML_DIR / "survey_2026_09"
            / "10_insert_survey_role_permissions.sql").read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"--[^\n]*", "", diez)

    assert _grants_de_rol_in(sin_comentarios, "titulatec_tech_management") == {
        "titulatec.survey_review.page.list",
        "titulatec.survey_review.api.approve",
        "titulatec.survey_review.api.reject",
        "titulatec.survey.page.list",
        "titulatec.survey.api.read",
        "titulatec.survey.api.export",
        "titulatec.survey.api.manage",
        "titulatec.notifications.api.read.own",
        "titulatec.notifications.api.mark_read",
    }, "GTV (titulatec_tech_management) no tiene exactamente los 9 permisos del reparto"

    conservados = _grants_de_rol_in(sin_comentarios, "titulatec_school_services_head")
    for codigo in ("titulatec.enrollment_request.page.list",
                   "titulatec.enrollment_request.api.approve",
                   "titulatec.enrollment_request.api.reject",
                   "titulatec.process.api.requirement.mark"):
        assert codigo in conservados, (
            f"la jefatura deberia conservar {codigo} (spec D12: solo pierde survey.*)")

    assert re.search(
        r"DELETE\s+FROM\s+core_role_permissions[^;]*"
        r"r\.name\s*=\s*'titulatec_school_services_head'[^;]*"
        r"LIKE\s*'titulatec\.survey\.%'",
        sin_comentarios,
    ), ("falta el DELETE que le quita 'titulatec.survey.%' a la jefatura "
        "(patron acotado como 03_insert_role_permissions.sql:150-155)")


@requires_dml
def test_el_patron_like_de_survey_no_alcanza_a_survey_review():
    """El DELETE de arriba usa `LIKE 'titulatec.survey.%'`: el punto literal
    tras "survey" no casa con el `_` de `titulatec.survey_review.*`, asi que
    GTV no pierde los 3 permisos que acaba de recibir. Si alguien "simplifica"
    el patron a `titulatec.survey%` (sin el punto), este test lo detecta."""
    diez = (DML_DIR / "survey_2026_09"
            / "10_insert_survey_role_permissions.sql").read_text(encoding="utf-8")

    m = re.search(r"LIKE\s*'([^']+)'", diez)
    assert m, "no se encontro ningun patron LIKE en el archivo 10"
    patron = _like_to_regex(m.group(1))

    assert patron.match("titulatec.survey.page.list")
    assert patron.match("titulatec.survey.api.manage")
    assert not patron.match("titulatec.survey_review.page.list")
    assert not patron.match("titulatec.survey_review.api.approve")
    assert not patron.match("titulatec.survey_review.api.reject")


# Los 23 permisos del alumno de titulacion. Los 21 originales colgaban de
# `student` hasta 2026-09-15, cuando pasaron a `graduate`; los 2 de
# `appointment.api.{book,cancel}.own` se agregaron el 2026-09-16 para el
# auto-agendado de citas de cotejo (nunca existieron en `student`).
PERMISOS_ALUMNO = (
    "titulatec.dashboard.student",
    "titulatec.process.page.my", "titulatec.process.api.read.own",
    "titulatec.process.api.advance",
    "titulatec.document.api.upload.own", "titulatec.document.api.read.own",
    "titulatec.document.api.delete.own",
    "titulatec.format_b.page.fill", "titulatec.format_b.api.save",
    "titulatec.format_b.api.submit", "titulatec.format_b.api.read.own",
    "titulatec.chat.page.view", "titulatec.chat.api.read", "titulatec.chat.api.send",
    "titulatec.chat.api.upload",
    "titulatec.appointment.page.my", "titulatec.appointment.api.confirm.own",
    "titulatec.appointment.api.book.own", "titulatec.appointment.api.cancel.own",
    "titulatec.ceremony.page.my", "titulatec.ceremony.api.upload.own",
    "titulatec.notifications.api.read.own", "titulatec.notifications.api.mark_read",
)
# Lo minimo de la plataforma (app `itcj`) que ya tenia `student`.
PERMISOS_PLATAFORMA_ALUMNO = ("core.general.read", "core.general.api.read")


def _grants_de_rol(sql: str, rol: str) -> set[str]:
    """Codigos de los `ARRAY[...]) WHERE r.name = '<rol>'` de un DML de grants.

    `[^\\]]*` y no `.*?`: un comodin no-greedy arrancaria en el ARRAY del bloque
    anterior y se tragaria sus codigos.
    """
    patron = (r"ARRAY\[([^\]]*)\]\)\s*WHERE\s+r\.name\s*=\s*'"
              + re.escape(rol) + "'")
    return {c for bloque in re.findall(patron, sql)
            for c in re.findall(r"'([^']+)'", bloque)}


@requires_dml
def test_el_alumno_de_titulacion_es_graduate_y_student_ya_no_recibe_nada_de_titulatec():
    """2026-09-15: el alumno deja de reciclar `student` (el de AgendaTec y el
    `role_id` de miles de cuentas). El 01 crea `graduate`; el 03 le da lo que tenia
    `student` en titulatec mas lo minimo de la plataforma, y le REVOCA a `student`
    todo lo de titulatec con un DELETE que se re-aplica en cada corrida (misma
    politica que los otros DELETE del 03)."""
    uno = re.sub(r"--[^\n]*", "",
                 (DML_DIR / "01_insert_roles.sql").read_text(encoding="utf-8"))
    assert "('graduate')" in uno, "el 01 no crea el rol graduate"

    tres = re.sub(r"--[^\n]*", "",
                  (DML_DIR / "03_insert_role_permissions.sql").read_text(encoding="utf-8"))
    assert _grants_de_rol(tres, "graduate") == (
        set(PERMISOS_ALUMNO) | set(PERMISOS_PLATAFORMA_ALUMNO))
    assert _grants_de_rol(tres, "student") == set(), "student ya no recibe permisos en el 03"
    assert re.search(
        r"DELETE\s+FROM\s+core_role_permissions[^;]*r\.name\s*=\s*'student'"
        r"[^;]*p\.app_id\s*=\s*v_app_id\s*;", tres), (
        "falta el DELETE que revoca a student los permisos de titulatec")
