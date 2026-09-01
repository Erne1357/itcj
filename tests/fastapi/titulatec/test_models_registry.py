"""Contrato: todo modelo de `models/` esta re-exportado y registrado.

Por que existe este test
------------------------
`models/__init__.py` es lo unico que hace visible un modelo de titulatec:

  - los services lo importan de ahi (`from itcj2.apps.titulatec.models import X`),
    asi que si falta el re-export el service revienta con `ImportError` en la
    primera llamada — en produccion, no al arrancar;
  - `migrations/env.py:33` importa el PAQUETE, no los submodulos: un modelo sin
    re-export queda fuera de `Base.metadata` y por tanto invisible para el
    `--autogenerate` de Alembic;
  - el `create_all` del CI (`.github/workflows/deploy.yml:76-101`) importa el
    mismo paquete: la tabla ni siquiera se crea en la BD de test.

Un olvido de una linea rompe las tres cosas a la vez y ninguna avisa al importar.

Como se enumeran los modelos esperados
--------------------------------------
Por AST de los archivos de `models/*.py`, sin importarlos: importar el submodulo
registraria la tabla en `Base.metadata` como efecto colateral y el test se
mentiria a si mismo.
"""
from __future__ import annotations

import ast
from pathlib import Path

MODELS_DIR = (Path(__file__).resolve().parents[3]
              / "itcj2" / "apps" / "titulatec" / "models")


def _declared_models() -> dict[str, str]:
    """{NombreDeClase -> __tablename__} de todo `class X(Base)` en models/."""
    found: dict[str, str] = {}
    for path in sorted(MODELS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "Base" for b in node.bases):
                continue
            table = None
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and stmt.targets[0].id == "__tablename__"
                        and isinstance(stmt.value, ast.Constant)):
                    table = stmt.value.value
            if table:
                found[node.name] = table
    return found


def test_hay_17_modelos_declarados():
    """Guarda del propio test: si el AST deja de ver clases, lo de abajo pasaria
    en verde sin verificar nada."""
    declared = _declared_models()

    assert len(declared) == 17, (
        f"se esperaban 17 modelos titulatec, el AST vio {len(declared)}: "
        f"{sorted(declared)}"
    )


def test_todos_los_modelos_estan_reexportados_en_models_init():
    """FALLA HOY: `CotejoRequirement` no esta en `models/__init__.py`.

    Consecuencia viva: `cotejo_requirement_service.py:26` hace
    `from itcj2.apps.titulatec.models import CotejoRequirement` y lanza
    `ImportError` en cuanto alguien lo llame. La tabla, la migracion, el permiso
    (`titulatec.cohort.api.cotejo_reqs`, seeder 07) y el parcial de la UI ya
    existen: es una feature a medio cablear, no un modelo muerto.

    El arreglo va en OTRO commit (TDD): agregar el import y la entrada en
    `__all__` de `itcj2/apps/titulatec/models/__init__.py`.
    """
    import itcj2.apps.titulatec.models as models

    declared = _declared_models()
    faltantes = sorted(name for name in declared if not hasattr(models, name))

    assert not faltantes, (
        "modelos declarados en models/*.py pero NO re-exportados en "
        f"models/__init__.py: {faltantes}. Rompe los imports de los services, "
        "el autogenerate de Alembic y el create_all del CI."
    )


def test_todos_los_modelos_estan_en_base_metadata():
    """Mismo olvido, visto desde el registro de SQLAlchemy.

    Se importa el PAQUETE, igual que `migrations/env.py:33` y el create_all del
    CI — nunca los submodulos: importarlos registraria la tabla y taparia el bug.
    """
    import itcj2.apps.titulatec.models  # noqa: F401
    from itcj2.models.base import Base

    declared = _declared_models()
    faltantes = sorted(table for table in declared.values()
                       if table not in Base.metadata.tables)

    assert not faltantes, (
        f"tablas fuera de Base.metadata al importar el paquete: {faltantes}. "
        "Alembic no las ve en --autogenerate y el create_all del CI no las crea."
    )


def test_los_reexports_coinciden_con___all__():
    """`__all__` es lo que documenta la superficie publica del paquete.

    Un import sin entrada en `__all__` (o al reves) deja el paquete inconsistente
    para `from ... import *` y para los lectores.
    """
    import itcj2.apps.titulatec.models as models

    exportados = {name for name in models.__all__}
    reales = {name for name in _declared_models() if hasattr(models, name)}

    assert exportados == reales, (
        f"solo en __all__: {sorted(exportados - reales)}; "
        f"importados pero fuera de __all__: {sorted(reales - exportados)}"
    )
