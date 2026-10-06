"""Fuente de una ruta de TitulaTec, seguida hasta su cuerpo sincrono.

Convencion de rutas (spec rendimiento 2026-10-05 §3.8, R7): una ruta que lee el
cuerpo de la peticion es `async def` solo para hacer ese `await` y delega TODO
lo demas en `return await run_in_threadpool(_cuerpo_<ruta>, ...)`. La ruta que
las pruebas estructurales (que leen el fuente o el AST) quieren inspeccionar es,
entonces, la ruta MAS su `_cuerpo_<ruta>`. Estos helpers siguen esa delegacion.
"""
from __future__ import annotations

import ast
import inspect
import textwrap


def _nombre(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def cuerpos_delegados(endpoint) -> list:
    """Funciones `_cuerpo_*` del mismo modulo a las que `endpoint` delega con
    `run_in_threadpool(_cuerpo_x, ...)`, en orden de aparicion."""
    arbol = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    modulo = inspect.getmodule(endpoint)
    salida = []
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and _nombre(nodo.func) == "run_in_threadpool"
                and nodo.args and isinstance(nodo.args[0], ast.Name)
                and nodo.args[0].id.startswith("_cuerpo_")):
            fn = getattr(modulo, nodo.args[0].id, None)
            if fn is not None and fn not in salida:
                salida.append(fn)
    return sorted(salida, key=lambda f: inspect.getsourcelines(f)[1])


def fuente_de_ruta(endpoint) -> str:
    """Fuente de la ruta + el de sus cuerpos sincronos (recursivo)."""
    partes = [inspect.getsource(endpoint)]
    for fn in cuerpos_delegados(endpoint):
        partes.append(fuente_de_ruta(fn))
    return "\n".join(partes)
