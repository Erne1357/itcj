"""El paquete de modelos re-exporta TODO lo que declara, sin importar submódulos.

Se enumera por AST a propósito: `Base.metadata` es global del proceso, así que un
`assert "x" in Base.metadata.tables` pasa por culpa de otro test que ya importó el
módulo. Aquí se comprueba el contrato del paquete, que es lo que consume el
create_all de CI.
"""
import ast
from pathlib import Path

import itcj2.apps.directory.models as models_pkg

_PKG_DIR = Path(models_pkg.__file__).parent


def _declared_model_classes():
    names = []
    for path in sorted(_PKG_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "Base":
                        names.append(node.name)
    return names


def test_every_model_is_reexported():
    declared = _declared_model_classes()
    assert declared, "no se encontró ningún modelo por AST"
    for name in declared:
        assert hasattr(models_pkg, name), f"{name} no está re-exportado en models/__init__.py"


def test_all_matches_reexports():
    assert set(models_pkg.__all__) == set(_declared_model_classes())


def test_expected_model_count():
    assert len(_declared_model_classes()) == 2
