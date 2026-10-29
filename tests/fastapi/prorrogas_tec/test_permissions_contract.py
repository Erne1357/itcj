"""Contrato: todo permiso que el CÓDIGO de Prórrogas exige debe existir en el DML.

`database/DML/` está en .gitignore: nada más ata los códigos de `require_perms`
/ `require_page_app` con lo que siembra `init-prorrogas`. Un código sin sembrar
da 403 a todo el mundo sin error en los logs. Se salta en CI (no hay DML).
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "itcj2" / "apps" / "prorrogas_tec"
DML = REPO / "database" / "DML" / "prorrogas_tec"
CODE_RE = re.compile(r"^prorrogas_tec\.[a-z_]+\.(api|page)\.[a-z_.]+$")


def _codes_in_code() -> set[str]:
    out = set()
    for f in [*APP.glob("api/**/*.py"), *APP.glob("pages/**/*.py")]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CODE_RE.match(node.value):
                out.add(node.value)
    return out


@pytest.mark.skipif(not DML.exists(), reason="database/ esta en .gitignore (CI)")
def test_todo_permiso_que_exige_el_codigo_esta_sembrado():
    sembrados = set(re.findall(r"'(prorrogas_tec\.[a-z_.]+)'",
                               "\n".join(p.read_text(encoding="utf-8") for p in DML.glob("*.sql"))))
    assert _codes_in_code() - sembrados == set()


def test_el_censo_no_esta_vacio():
    assert "prorrogas_tec.secretaria.page.view" in _codes_in_code()
