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
  `database/DML/titulatec/*.sql` (02 los declara todos; 07 anade
  `cohort.api.cotejo_reqs`).

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

    for path in sorted(DML_DIR.glob("*.sql")):
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
        "permanente. Agregalos a database/DML/titulatec/02_insert_permissions.sql "
        f"y asignalos en 03_insert_role_permissions.sql:\n{faltantes}"
    )


@requires_dml
def test_el_dml_declara_los_66_permisos_conocidos():
    """Guarda del OTRO lado: detecta un seeder truncado o borrado.

    66 es el numero verificado en BD tras `titulatec init-titulatec`
    (CLAUDE.md de la app, §9). Si baja, alguien recorto el 02; si sube, el
    numero de esta asercion se actualiza junto con la doc.
    """
    declared = _declared_by_dml()

    assert len(declared) == 66, (
        f"el DML declara {len(declared)} permisos titulatec, se esperaban 66. "
        "Actualiza este numero SOLO si el cambio en database/DML/titulatec/ es "
        f"intencional. Declarados: {sorted(declared)}"
    )
