"""El seed mínimo de la suite cubre TODA app sobre la que el código pone un gate.

Por qué existe este guard
-------------------------
El gate de CI construye la BD vacía con ``create_all`` y la puebla con el
fixture ``_seed_minimal_reference_data`` de ``tests/fastapi/conftest.py``.
``database/`` está gitignored a propósito (trae PII real), así que en CI no hay
más filas de referencia que las de ese fixture.

En la BD de desarrollo, en cambio, las nueve filas de ``core_apps`` existen
desde hace tiempo. Esa diferencia hace que un test que consulta ``core_apps``
de verdad pase en local y solo reviente en CI — y como la app nueva se
desarrolla en una rama, el fallo no aparece hasta el merge a ``main``, que es
justo cuando bloquea el deploy.

Pasó de verdad: el fixture sembraba tres apps y ``tests/fastapi/adhoc/`` daba
20 fallos y 15 errores contra una BD limpia, todos con el mismo mensaje —
``App 'adhoc' no existe o está inactiva``— y ninguno visible en desarrollo.

Este guard convierte ese fallo diferido en uno inmediato: si alguien registra
una app y se olvida del seed, falla aquí, con el nombre de la app y la línea
que hay que tocar.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text

RAIZ = Path(__file__).resolve().parents[3]
CODIGO = RAIZ / "itcj2"
CONFTEST = RAIZ / "tests" / "fastapi" / "conftest.py"

#: Las cuatro formas de exigir una app en este código. La clave es siempre el
#: primer argumento y siempre un literal.
RE_GATE = re.compile(
    r'require_(?:page_)?(?:app|perms|roles)\(\s*"(?P<clave>[a-z_-]+)"'
)


def _apps_con_gate() -> set[str]:
    """Claves de app que el código exige en algún endpoint o página."""
    claves: set[str] = set()
    for ruta in CODIGO.rglob("*.py"):
        for m in RE_GATE.finditer(ruta.read_text(encoding="utf8", errors="ignore")):
            claves.add(m.group("clave"))
    return claves


def _apps_en_el_seed() -> set[str]:
    """Claves que el fixture inserta en ``core_apps``."""
    fuente = CONFTEST.read_text(encoding="utf8")
    bloque = re.search(
        r"INSERT INTO core_apps.*?ON CONFLICT", fuente, re.S
    )
    assert bloque, "no se encontró el INSERT de core_apps en el conftest"
    return set(re.findall(r"\('([a-z_-]+)',", bloque.group(0)))


def test_el_codigo_declara_gates_de_app():
    """Red de seguridad del propio guard: si el regex deja de casar, avisa."""
    claves = _apps_con_gate()
    assert len(claves) >= 5, (
        "El escaneo encontró muy pocas apps con gate "
        f"({sorted(claves)}). O el regex dejó de casar con la forma de "
        "`require_app(...)`, o este guard está mirando el sitio equivocado — "
        "en cualquiera de los dos casos ya no protege nada."
    )


def test_toda_app_con_gate_esta_en_el_seed():
    faltan = sorted(_apps_con_gate() - _apps_en_el_seed())
    assert not faltan, (
        "Estas apps tienen un gate en el código pero NO están en el seed de "
        f"`tests/fastapi/conftest.py`: {faltan}.\n"
        "En la BD de desarrollo la fila existe, así que los tests que la "
        "consultan pasan en local y revientan en CI, donde la BD se construye "
        "vacía con create_all. El mensaje que verías allí es "
        "\"App '<clave>' no existe o está inactiva\".\n"
        "Arreglo: añadir la fila al INSERT de `core_apps` del fixture "
        "`_seed_minimal_reference_data`, NO a `database/DML/` (que no llega al "
        "checkout de CI)."
    )


@pytest.mark.parametrize("clave", sorted(_apps_con_gate()))
def test_la_app_esta_de_verdad_en_la_bd_de_test(db_session, clave):
    """No basta con que la línea esté escrita: la fila tiene que existir.

    Comprueba el resultado del fixture, no su código fuente — que es lo que de
    verdad ve `get_or_404_app` cuando corre un test.
    """
    fila = db_session.execute(
        text("SELECT is_active FROM core_apps WHERE key = :k"), {"k": clave}
    ).fetchone()
    assert fila is not None, (
        f"`core_apps` no tiene la fila de '{clave}' en la BD de test. "
        "El fixture `_seed_minimal_reference_data` debería haberla insertado."
    )
    assert fila[0] is True, (
        f"La app '{clave}' está en `core_apps` pero inactiva: "
        "`get_or_404_app` la trata igual que si no existiera."
    )
