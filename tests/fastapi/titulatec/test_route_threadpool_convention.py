"""R7 (spec rendimiento 2026-10-05 §3.8, hallazgos H3/H8/H9): convencion de las
rutas de TitulaTec respecto al event loop.

Las rutas de `itcj2/apps/titulatec/pages/*.py` abren una sesion SINCRONA de
SQLAlchemy y hacen trabajo bloqueante (consultas, plantillas, correo, hashing).
Una `async def` corre ese trabajo EN el event loop y congela al worker entero.
La forma canonica es:

* sin `await` -> `def` (FastAPI la corre en el threadpool);
* con `await` del cuerpo (`await request.form()`, `await archivo.read()`) ->
  `async def` que hace ese `await` y luego
  `return await run_in_threadpool(_cuerpo_xxx, ...)`, con `_cuerpo_xxx` una
  funcion SINCRONA del mismo modulo que abre y cierra `SessionLocal()`.

Esta prueba lo fija por AST (sin levantar la app):

1. toda funcion decorada con `@router.<verbo>` que sea `async def` tiene por lo
   menos un `await` propio;
2. su cuerpo `async` no llama a `SessionLocal(`, ni a un `*Service.` ni a
   `render_titulatec(`, salvo dentro de un argumento de `run_in_threadpool(...)`;
3. su ULTIMA sentencia es `return await run_in_threadpool(<sincrona>, ...)`: la
   ruta `async` existe solo para leer el cuerpo y delegar, no para terminar el
   trabajo en el loop.

Las excepciones van en `EXCEPCIONES` con su justificacion. Una excepcion que ya
no hace falta (la ruta se arreglo o desaparecio) tambien falla: la lista no
puede acumular basura.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec" / "pages"

_VERBOS = {"get", "post", "put", "delete", "patch", "head", "options"}

# (archivo, funcion) -> justificacion. Vacia a proposito: se llena solo si una
# ruta NO puede seguir la convencion sin cambiar su comportamiento.
EXCEPCIONES: dict[tuple[str, str], str] = {}


def _es_ruta(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for dec in fn.decorator_list:
        call = dec if isinstance(dec, ast.Call) else None
        func = call.func if call else dec
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _VERBOS
            and isinstance(func.value, ast.Name)
            and func.value.id == "router"
        ):
            return True
    return False


def _rutas() -> list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    salida = []
    for archivo in sorted(PAGES.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in arbol.body:
            if isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)) and _es_ruta(nodo):
                salida.append((archivo.name, nodo))
    return salida


def _propios(fn: ast.AST):
    """Nodos del cuerpo de `fn` SIN bajar a funciones/lambdas anidadas: un
    `await` o una llamada dentro de una funcion interna no es del cuerpo `async`
    de la ruta."""
    pila = list(ast.iter_child_nodes(fn))
    while pila:
        nodo = pila.pop()
        yield nodo
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pila.extend(ast.iter_child_nodes(nodo))


def _nombre_llamada(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def _raiz(expr: ast.AST) -> str | None:
    while isinstance(expr, ast.Attribute):
        expr = expr.value
    return expr.id if isinstance(expr, ast.Name) else None


def _dentro_de_threadpool(fn: ast.AST) -> set[int]:
    """`id()` de todos los nodos que viven en los argumentos de un
    `run_in_threadpool(...)` (o `anyio.to_thread.run_sync`)."""
    dentro: set[int] = set()
    for nodo in _propios(fn):
        if isinstance(nodo, ast.Call) and _nombre_llamada(nodo) in {"run_in_threadpool", "run_sync"}:
            for hijo in [*nodo.args, *[k.value for k in nodo.keywords]]:
                for n in ast.walk(hijo):
                    dentro.add(id(n))
    return dentro


def _termina_delegando(fn: ast.AsyncFunctionDef) -> bool:
    """La ultima sentencia es `return await run_in_threadpool(<nombre>, ...)`."""
    ultima = fn.body[-1]
    return (
        isinstance(ultima, ast.Return)
        and isinstance(ultima.value, ast.Await)
        and isinstance(ultima.value.value, ast.Call)
        and _nombre_llamada(ultima.value.value) == "run_in_threadpool"
        and bool(ultima.value.value.args)
        and isinstance(ultima.value.value.args[0], ast.Name)
    )


def _infracciones(fn: ast.AsyncFunctionDef) -> list[str]:
    fuera = _dentro_de_threadpool(fn)
    malas: list[str] = []
    if not any(isinstance(n, ast.Await) for n in _propios(fn)):
        malas.append("es `async def` sin ningun `await` (debe ser `def`)")
    elif not _termina_delegando(fn):
        malas.append("no termina en `return await run_in_threadpool(_cuerpo_xxx, ...)`")
    for nodo in _propios(fn):
        if not isinstance(nodo, ast.Call) or id(nodo) in fuera:
            continue
        nombre = _nombre_llamada(nodo)
        if nombre == "SessionLocal":
            malas.append(f"linea {nodo.lineno}: abre `SessionLocal()` en el cuerpo async")
        elif nombre == "render_titulatec":
            malas.append(f"linea {nodo.lineno}: renderiza una plantilla en el cuerpo async")
        elif isinstance(nodo.func, ast.Attribute):
            raiz = _raiz(nodo.func)
            if raiz and raiz.endswith("Service"):
                malas.append(f"linea {nodo.lineno}: llama a `{raiz}.{nodo.func.attr}` en el cuerpo async")
    return malas


def test_el_censo_de_rutas_no_esta_vacio():
    """Guarda contra una prueba que pasa en vacio por un cambio de ruta/decorador."""
    rutas = _rutas()
    assert len(rutas) >= 120, f"solo se encontraron {len(rutas)} rutas @router.<verbo>"


def test_las_rutas_async_siguen_la_convencion_del_threadpool():
    """Cada ruta `async def` hace un `await` real y no trabaja en el loop."""
    reporte: list[str] = []
    for archivo, fn in _rutas():
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        if (archivo, fn.name) in EXCEPCIONES:
            continue
        for mala in _infracciones(fn):
            reporte.append(f"{archivo}::{fn.name}: {mala}")
    assert not reporte, (
        f"{len(reporte)} infracciones de la convencion §3.8 (def sin await / "
        "run_in_threadpool del cuerpo):\n" + "\n".join(reporte)
    )


def test_las_excepciones_estan_justificadas_y_vigentes():
    """Una excepcion necesita justificacion, y debe seguir siendo necesaria."""
    por_ruta = {(a, fn.name): fn for a, fn in _rutas()}
    for (archivo, nombre), motivo in EXCEPCIONES.items():
        assert motivo.strip(), f"{archivo}::{nombre}: excepcion sin justificacion"
        fn = por_ruta.get((archivo, nombre))
        assert fn is not None, f"{archivo}::{nombre}: la excepcion apunta a una ruta que no existe"
        assert isinstance(fn, ast.AsyncFunctionDef) and _infracciones(fn), (
            f"{archivo}::{nombre}: ya cumple la convencion, quitala de EXCEPCIONES"
        )


def test_ninguna_ruta_def_hace_await_ni_se_pierde_el_decorador():
    """Una `def` (sincrona) no puede contener `await` (SyntaxError al importar);
    se verifica por AST que ninguna ruta sincrona quedo con uno suelto."""
    for archivo, fn in _rutas():
        if isinstance(fn, ast.FunctionDef):
            assert not any(isinstance(n, ast.Await) for n in _propios(fn)), f"{archivo}::{fn.name}"


@pytest.mark.parametrize("archivo", sorted(p.name for p in PAGES.glob("*.py") if p.name != "__init__.py"))
def test_los_cuerpos_privados_son_sincronos(archivo):
    """`_cuerpo_xxx` que usa `run_in_threadpool` debe ser funcion sincrona:
    un `run_in_threadpool(<corrutina>)` no corre nada en el hilo."""
    arbol = ast.parse((PAGES / archivo).read_text(encoding="utf-8"))
    asincronas = {
        n.name for n in ast.walk(arbol) if isinstance(n, ast.AsyncFunctionDef)
    }
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and _nombre_llamada(nodo) == "run_in_threadpool" and nodo.args:
            primero = nodo.args[0]
            if isinstance(primero, ast.Name):
                assert primero.id not in asincronas, (
                    f"{archivo}:{nodo.lineno}: run_in_threadpool({primero.id}) pero "
                    f"`{primero.id}` es `async def`"
                )


# ---------------------------------------------------------------------------
# El verificador mismo: sin esto, una prueba que nunca falla pasaria igual.
# ---------------------------------------------------------------------------
def _fn(*lineas: str) -> ast.AsyncFunctionDef:
    return ast.parse(chr(10).join(lineas) + chr(10)).body[0]


def test_el_verificador_marca_una_ruta_async_sin_await():
    fn = _fn(
        "async def r():",
        "    db = SessionLocal()",
    )
    malas = _infracciones(fn)
    assert any("sin ningun `await`" in m for m in malas)
    assert any("SessionLocal" in m for m in malas)


def test_el_verificador_marca_un_servicio_o_una_plantilla_en_el_loop():
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    ProcessService.cancel(db, 1)",
        "    render_titulatec(request, 'x.html', {})",
        "    return await run_in_threadpool(_cuerpo_r, form=form)",
    )
    malas = _infracciones(fn)
    assert any("ProcessService.cancel" in m for m in malas)
    assert any("plantilla" in m for m in malas)


def test_el_verificador_exige_terminar_delegando_al_threadpool():
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    return Response()",
    )
    assert any("run_in_threadpool" in m for m in _infracciones(fn))


def test_el_verificador_acepta_la_forma_canonica():
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    return await run_in_threadpool(_cuerpo_r, request=request, form=form)",
    )
    assert _infracciones(fn) == []


def test_un_servicio_dentro_de_run_in_threadpool_no_cuenta_como_trabajo_en_el_loop():
    fn = _fn(
        "async def r(request):",
        "    raw = await request.body()",
        "    previo = await run_in_threadpool(DocumentService.validate, raw=raw)",
        "    return await run_in_threadpool(_cuerpo_r, previo=previo)",
    )
    assert _infracciones(fn) == []
