"""Rutas de la API de tickets y asignaciones de maint: nada síncrono en el event loop.

Perf 2026-10-07: eran `async def` con BD síncrona (SQLAlchemy de sesión) y, en
asignar/resolver/cancelar, además el correo de Graph EN LÍNEA (~400 ms con
`requests`). En una `async def` eso congela el event loop del worker entero
mientras dura: ninguna otra petición del proceso avanza. Como `def`, FastAPI
las corre en el threadpool.

Regla que fija este archivo (la misma que `test_route_threadpool_convention.py`
de titulatec): una función de ruta de estos módulos es `def`, o es `async def`
y contiene al menos un `await` (si alguna vez hace falta trabajo async real).
"""
import ast
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "maint" / "api"
_MODULES = ["tickets.py", "assignments.py"]
_ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete"}


def _rutas(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in _ROUTE_DECORATORS):
                yield node
                break


@pytest.mark.parametrize("modulo", _MODULES)
def test_ninguna_ruta_async_sin_await(modulo):
    malas = []
    for fn in _rutas(_API / modulo):
        if isinstance(fn, ast.AsyncFunctionDef):
            if not any(isinstance(n, ast.Await) for n in ast.walk(fn)):
                malas.append(fn.name)
    assert malas == [], (
        f"{modulo}: rutas `async def` sin ningún `await` (bloquean el event loop "
        f"con BD/correo síncronos; deben ser `def`): {malas}")


@pytest.mark.parametrize("modulo", _MODULES)
def test_el_modulo_tiene_rutas(modulo):
    assert list(_rutas(_API / modulo)), "el detector de rutas no encontró ninguna"
