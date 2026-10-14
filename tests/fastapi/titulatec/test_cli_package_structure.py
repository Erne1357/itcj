"""Estructura del paquete `itcj2/cli/titulatec/` (spec 2026-10-14-titulatec-cli-paquete §3-§4).

El CLI de TitulaTec dejó de ser un solo archivo de ~4,900 líneas: es un paquete
con un módulo por contexto. Aquí se fija lo que ese corte no puede romper:

- los 28 comandos siguen registrados en `titulatec_cli` con los mismos nombres
  (y cada uno vive en el módulo que le asigna la spec);
- `itcj2.cli.titulatec` sigue exportando lo que usan `cli/main.py` y
  `cli/core.py` (`titulatec_cli`, `SEED_FILES`, `DML_TITULATEC`, `PROJECT_ROOT`);
- `PROJECT_ROOT` es la raíz del repo (si sube un nivel de menos, TODOS los
  comandos dicen «faltan archivos en disco»);
- ningún nombre de nivel superior está definido en dos módulos (un helper
  compartido vive en `_common`/`verificaciones`, no copiado);
- los submódulos de comandos solo dependen de `_common` y `verificaciones`
  (sin ciclos entre ellos);
- ningún módulo pasa de ~800 líneas.

Sin BD y sin `database/` en disco: corre en CI.
"""
from __future__ import annotations

import ast
from pathlib import Path

import itcj2.cli.titulatec as paquete
from itcj2.cli.titulatec import DML_TITULATEC, PROJECT_ROOT, SEED_FILES, titulatec_cli

_PKG = "itcj2.cli.titulatec"
_REPO = Path(__file__).resolve().parents[3]
_DIR = _REPO / "itcj2" / "cli" / "titulatec"

# Spec §3: comando -> módulo. Literal a propósito: mover un comando de módulo
# o renombrarlo es una decisión que este test obliga a hacer explícita.
_COMANDO_A_MODULO = {
    "init-titulatec": "seed",
    "init-email-tasks": "deltas",
    "init-outbox-admin": "deltas",
    "init-bitacora": "deltas",
    "init-reportes": "deltas",
    "init-especialidades": "deltas",
    "init-ajustes-2026-10": "deltas",
    "init-posgrado": "posgrado",
    "init-biblioteca-caja": "biblioteca",
    "activar-biblioteca-caja": "biblioteca",
    "import-prior-clearances": "liberaciones",
    "emitir-folios-previos": "liberaciones",
    "load-survey-2026-09": "encuesta",
    "import-survey-xlsx": "encuesta",
    "sii-ping": "sii",
    "sii-rules-validate": "sii",
    "sii-check": "sii",
    "sii-sweep": "sii",
    "audit-purge": "bitacora",
    "audit-backfill-solicitudes": "bitacora",
    "fix-missing-credentials": "mantenimiento",
    "rename-documents": "mantenimiento",
    "fix-control-l": "mantenimiento",
    "exportar-sin-cuenta": "nips",
    "cargar-nips": "nips",
    "purgar-nips": "nips",
    "exportar-controles": "promedios",
    "cargar-promedios": "promedios",
}
_MODULOS_DE_COMANDOS = set(_COMANDO_A_MODULO.values())
_MODULOS = _MODULOS_DE_COMANDOS | {"_common", "verificaciones"}
_MAX_LINEAS = 800


def _modulos() -> dict[str, Path]:
    return {p.stem: p for p in sorted(_DIR.glob("*.py"))}


def _imports_del_paquete(ruta: Path) -> set[str]:
    """Submódulos de `itcj2.cli.titulatec` que importa `ruta` (en cualquier nivel)."""
    tree = ast.parse(ruta.read_text(encoding="utf-8"))
    vistos: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                vistos.add(node.module.split(".")[0])
            elif node.module.startswith(_PKG + "."):
                vistos.add(node.module[len(_PKG) + 1:].split(".")[0])
            elif node.module == _PKG:
                vistos.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(_PKG + "."):
                    vistos.add(a.name[len(_PKG) + 1:].split(".")[0])
    return vistos


def test_es_un_paquete_con_sus_13_modulos():
    assert Path(paquete.__file__).name == "__init__.py", (
        "itcj2.cli.titulatec debe ser un paquete, no el archivo de 4,870 líneas")
    assert not (_REPO / "itcj2" / "cli" / "titulatec.py").exists()
    assert set(_modulos()) == _MODULOS | {"__init__"}
    assert len(_MODULOS) == 13


def test_registra_los_28_comandos_con_los_mismos_nombres():
    assert set(titulatec_cli.commands) == set(_COMANDO_A_MODULO)
    assert len(titulatec_cli.commands) == 28


def test_cada_comando_vive_en_el_modulo_de_la_spec():
    fuera_de_lugar = {
        nombre: cmd.callback.__module__
        for nombre, cmd in titulatec_cli.commands.items()
        if cmd.callback.__module__ != f"{_PKG}.{_COMANDO_A_MODULO[nombre]}"
    }
    assert not fuera_de_lugar, fuera_de_lugar


def test_el_cli_principal_registra_el_mismo_grupo():
    from itcj2.cli.main import cli

    assert cli.commands["titulatec"] is titulatec_cli


def test_reexporta_los_nombres_que_usan_main_y_core():
    """Son LOS MISMOS objetos de `_common` (no copias): `main.py` y `core.py`
    importan del paquete y deben ver el grupo y la lista con los que trabajan
    los submódulos."""
    from itcj2.cli.titulatec import _common

    for nombre in ("titulatec_cli", "SEED_FILES", "DML_TITULATEC", "PROJECT_ROOT"):
        assert getattr(paquete, nombre) is getattr(_common, nombre), nombre


def test_project_root_es_la_raiz_del_repo():
    """`PROJECT_ROOT/database` es `<repo>/database` aunque `database/` no esté
    en el checkout (CI): se compara contra la raíz que ve este archivo."""
    assert PROJECT_ROOT == _REPO
    assert (PROJECT_ROOT / "asgi.py").is_file()
    assert DML_TITULATEC == _REPO / "database" / "DML" / "titulatec"


def test_core_deriva_sus_seeders_del_paquete():
    from itcj2.cli.core import _titulatec_seed_files

    assert _titulatec_seed_files() == [f"titulatec/{n}" for n in SEED_FILES]
    assert SEED_FILES[0] == "00_insert_app.sql"
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


def test_ningun_nombre_de_nivel_superior_esta_en_dos_modulos():
    donde: dict[str, list[str]] = {}
    for nombre, ruta in _modulos().items():
        if nombre == "__init__":
            continue
        for node in ast.parse(ruta.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                donde.setdefault(node.name, []).append(nombre)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        donde.setdefault(t.id, []).append(nombre)
    duplicados = {n: ms for n, ms in donde.items() if len(ms) > 1}
    assert not duplicados, duplicados


def test_los_modulos_de_comandos_solo_dependen_de_common_y_verificaciones():
    permitidos = {
        "_common": set(),
        "verificaciones": {"_common"},
        **{m: {"_common", "verificaciones"} for m in _MODULOS_DE_COMANDOS},
    }
    malos = {
        nombre: sorted(_imports_del_paquete(ruta) - permitidos[nombre])
        for nombre, ruta in _modulos().items()
        if nombre != "__init__" and _imports_del_paquete(ruta) - permitidos[nombre]
    }
    assert not malos, malos


def test_init_importa_todos_los_submodulos():
    """Un submódulo que `__init__` no importa no registra sus comandos."""
    assert _imports_del_paquete(_DIR / "__init__.py") >= _MODULOS


def test_ningun_modulo_supera_800_lineas():
    largos = {
        nombre: n
        for nombre, ruta in _modulos().items()
        if (n := len(ruta.read_text(encoding="utf-8").splitlines())) > _MAX_LINEAS
    }
    assert not largos, largos
