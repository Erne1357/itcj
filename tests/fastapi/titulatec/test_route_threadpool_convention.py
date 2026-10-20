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

Esta prueba lo fija por AST (sin levantar la app), con una LISTA BLANCA: el
cuerpo de una ruta `async` solo puede contener las llamadas de abajo. Cualquier
otra (un `*Service.` calificado como `mod.FooService.x()`, un `SessionLocal`
con alias, un ayudante que abre sesion, un `render_titulatec`, un
`hash_nip`, una llamada evaluada en el momento dentro de los argumentos de
`run_in_threadpool`) falla. Una lista negra de nombres se queda corta: basta un
alias o un modulo delante para esquivarla.

Reglas, por cada funcion decorada con `@router.<verbo>` que sea `async def`:

1. tiene por lo menos un `await` propio (si no, debe ser `def`);
2. cada llamada de su cuerpo esta en `_LLAMADAS_PERMITIDAS`, es un metodo de
   lectura del cuerpo de la peticion (`_METODOS_DE_CUERPO`), una guarda de
   configuracion pura (`GUARDAS_DE_CONFIGURACION`) o un
   `run_in_threadpool(<nombre>, <argumentos sin llamadas>)`;
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

# Llamadas por nombre simple que valen en el cuerpo async: construir/medir la
# respuesta o el form, sin tocar BD, red, disco ni plantillas.
_LLAMADAS_PERMITIDAS: dict[str, str] = {
    "dict": "normaliza el FormData ya leido (`dict(await request.form())`)",
    "Response": "respuesta de una guarda (411/413/204/404...)",
    "_hdr": "percent-codifica el mensaje de `X-Tt-Error` de una guarda",
    "_declared_body_size": (
        "lee `Content-Length` de las cabeceras: la guarda de tamano que tiene que "
        "correr ANTES de bufferear el cuerpo (public.py)"
    ),
}

# `<nombre>.<metodo>()`: lo UNICO que justifica que la ruta siga siendo `async`.
_METODOS_DE_CUERPO = {"form", "read", "body", "json"}

# Guardas que SOLO leen configuracion (`get_settings()`), ni BD, ni red, ni
# disco, y que por eso viven en el cuerpo async: tienen que responder ANTES de
# leer el cuerpo de la peticion, igual que antes de R7 (spec invariante 3).
# nombre -> (archivo donde se define, relativo a `itcj2/apps/titulatec/`, motivo).
GUARDAS_DE_CONFIGURACION: dict[str, tuple[str, str]] = {
    "_mode_block": (
        "pages/access_admin.py",
        "400 si la accion no es del modo vigente (`TITULATEC_ENROLLMENT_REVIEWER`)",
    ),
    "_alternate_mode_block": (
        "pages/requests_admin.py",
        "400 en modo alterno (`TITULATEC_ENROLLMENT_REVIEWER`)",
    ),
    "_recheck_block": (
        "pages/requests_admin.py",
        "400 si el modo no es `sii` o el SII esta deshabilitado (`TITULATEC_SII_BACKEND`)",
    ),
    "printing_enabled": (
        "services/certificate_service.py",
        "404 con la impresion de constancias apagada (`TITULATEC_CERTIFICATE_PRINTING`)",
    ),
}


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
    """Nodos del CUERPO de `fn` (no decoradores ni defaults de la firma) SIN bajar
    a funciones/lambdas anidadas: un `await` o una llamada dentro de una funcion
    interna no es del cuerpo `async` de la ruta."""
    pila = list(getattr(fn, "body", []))
    while pila:
        nodo = pila.pop()
        yield nodo
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pila.extend(ast.iter_child_nodes(nodo))


def _nombre_llamada(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def _es_nombre_o_atributo(expr: ast.AST) -> bool:
    """`nombre` o `a.b.c` (cadena de atributos sobre un nombre), sin llamadas."""
    while isinstance(expr, ast.Attribute):
        expr = expr.value
    return isinstance(expr, ast.Name)


def _tiene_llamadas(expr: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) for n in ast.walk(expr))


def _argumentos(call: ast.Call) -> list[ast.AST]:
    return [*call.args, *[k.value for k in call.keywords]]


def _llamada_no_permitida(call: ast.Call) -> str | None:
    """Motivo si `call` NO esta en la lista blanca; `None` si esta permitida."""
    f = call.func
    texto = ast.unparse(call)
    if len(texto) > 90:
        texto = texto[:87] + "..."

    # run_in_threadpool(<nombre|atributo>, <argumentos SIN llamadas>)
    if isinstance(f, ast.Name) and f.id == "run_in_threadpool":
        if not call.args or not _es_nombre_o_atributo(call.args[0]):
            return f"`{texto}`: el primer argumento de run_in_threadpool debe ser una funcion por nombre"
        for arg in [*call.args[1:], *[k.value for k in call.keywords]]:
            if _tiene_llamadas(arg):
                return (
                    f"`{texto}`: un argumento de run_in_threadpool llama a algo "
                    "(se evalua en el event loop ANTES de pasar al hilo)"
                )
        return None

    # `<nombre>.form()` / `.read()` / `.body()` / `.json()`
    if (
        isinstance(f, ast.Attribute)
        and f.attr in _METODOS_DE_CUERPO
        and isinstance(f.value, ast.Name)
    ):
        return None

    if isinstance(f, ast.Name) and (f.id in _LLAMADAS_PERMITIDAS or f.id in GUARDAS_DE_CONFIGURACION):
        # Las llamadas anidadas en sus argumentos se revisan por su cuenta: el
        # recorrido del cuerpo las visita todas.
        return None

    return f"llamada no permitida en el cuerpo async: `{texto}`"


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
    malas: list[str] = []
    if not any(isinstance(n, ast.Await) for n in _propios(fn)):
        malas.append("es `async def` sin ningun `await` (debe ser `def`)")
    elif not _termina_delegando(fn):
        malas.append("no termina en `return await run_in_threadpool(_cuerpo_xxx, ...)`")
    for nodo in sorted((n for n in _propios(fn) if isinstance(n, ast.Call)), key=lambda n: n.lineno):
        motivo = _llamada_no_permitida(nodo)
        if motivo:
            malas.append(f"linea {nodo.lineno}: {motivo}")
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
# Las guardas de la lista blanca: solo leen configuracion
# ---------------------------------------------------------------------------
_NOMBRES_DE_BD_O_RED = {"SessionLocal", "db", "session", "open", "requests", "httpx", "urlopen"}


def _def_de(nombre: str, relativo: str) -> ast.FunctionDef:
    ruta = PAGES.parent / relativo
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"{relativo}: no define `{nombre}`")


@pytest.mark.parametrize("guarda", sorted(GUARDAS_DE_CONFIGURACION))
def test_las_guardas_permitidas_solo_leen_configuracion(guarda):
    """La lista blanca confia en estas funciones porque no tocan BD, red ni disco.
    Si una dejara de ser pura (abre una sesion, llama a un servicio de BD), esta
    prueba la saca de la lista y la ruta que la usa debe moverla al cuerpo sincrono."""
    relativo, motivo = GUARDAS_DE_CONFIGURACION[guarda]
    assert motivo.strip()
    fn = _def_de(guarda, relativo)
    assert isinstance(fn, ast.FunctionDef), f"{guarda} debe ser sincrona"
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Name):
            assert nodo.id not in _NOMBRES_DE_BD_O_RED, (
                f"{relativo}::{guarda} usa `{nodo.id}`: ya no es una guarda de configuracion pura"
            )
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
            # `.query()`, `.execute()`, `.commit()`...: BD. `reviewer_mode`, `backend`,
            # `sii_configured` y `get_settings` son lecturas de configuracion.
            assert nodo.func.attr not in {"query", "execute", "commit", "flush", "add", "scalar", "scalars"}, (
                f"{relativo}::{guarda} llama a `.{nodo.func.attr}()`"
            )


def test_cada_guarda_de_la_lista_blanca_se_usa_en_alguna_ruta_async():
    """Una guarda en la lista blanca que ninguna ruta usa es una puerta abierta sin
    motivo: se quita."""
    usadas: set[str] = set()
    for _archivo, fn in _rutas():
        if isinstance(fn, ast.AsyncFunctionDef):
            for nodo in _propios(fn):
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                    usadas.add(nodo.func.id)
    sobran = set(GUARDAS_DE_CONFIGURACION) - usadas
    assert not sobran, f"guardas en la lista blanca que ninguna ruta async usa: {sorted(sobran)}"


# ---------------------------------------------------------------------------
# El verificador mismo: sin esto, una prueba que nunca falla pasaria igual.
# ---------------------------------------------------------------------------
def _fn(*lineas: str) -> ast.AsyncFunctionDef:
    return ast.parse(chr(10).join(lineas) + chr(10)).body[0]


def _con_form(*medio: str) -> ast.AsyncFunctionDef:
    """Ruta async con el `await` y la delegacion canonicos, mas `medio` entre ellos."""
    return _fn(
        "async def r(request):",
        "    form = await request.form()",
        *[f"    {linea}" for linea in medio],
        "    return await run_in_threadpool(_cuerpo_r, request=request, form=form)",
    )


def test_el_verificador_marca_una_ruta_async_sin_await():
    fn = _fn(
        "async def r():",
        "    db = SessionLocal()",
    )
    malas = _infracciones(fn)
    assert any("sin ningun `await`" in m for m in malas)
    assert any("SessionLocal" in m for m in malas)


def test_el_verificador_marca_un_servicio_calificado_por_modulo():
    """`elig.EligibilityService.sii_configured()` (requests_admin.py) tiene la raiz
    `elig`: una regla por nombre de raiz no la veia."""
    malas = _infracciones(_con_form("x = mod.FooService.x()"))
    assert any("mod.FooService.x()" in m for m in malas), malas


def test_el_verificador_marca_un_servicio_directo_y_una_plantilla():
    malas = _infracciones(_con_form("ProcessService.cancel(db, 1)", "render_titulatec(request, 'x.html', {})"))
    assert any("ProcessService.cancel" in m for m in malas)
    assert any("render_titulatec" in m for m in malas)


def test_el_verificador_marca_session_local_con_alias():
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    db = S()",
        "    return await run_in_threadpool(_cuerpo_r, form=form)",
    )
    assert any("S()" in m for m in _infracciones(fn))


def test_el_verificador_marca_una_llamada_evaluada_dentro_de_run_in_threadpool():
    """`run_in_threadpool(_cuerpo, db=SessionLocal())` abre la sesion EN el loop,
    antes de pasar al hilo: la lista blanca no deja llamadas en los argumentos."""
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    return await run_in_threadpool(_cuerpo_r, db=SessionLocal(), form=form)",
    )
    malas = _infracciones(fn)
    assert any("argumento de run_in_threadpool llama a algo" in m for m in malas), malas
    assert any("SessionLocal" in m for m in malas)


def test_el_verificador_marca_un_ayudante_que_abre_sesion():
    """Un ayudante como `_draft_congelada(user)` llamado DIRECTO desde el async
    abre sesion en el loop: debe ir como `run_in_threadpool(_draft_congelada, user)`."""
    malas = _infracciones(_con_form("if _draft_congelada(user):", "    return Response(status_code=204)"))
    assert any("_draft_congelada(user)" in m for m in malas), malas


def test_el_verificador_acepta_el_ayudante_dentro_de_un_salto_al_threadpool():
    fn = _fn(
        "async def r(request, user):",
        "    if await run_in_threadpool(_draft_congelada, user):",
        "        return Response(status_code=204)",
        "    data = await request.form()",
        "    return await run_in_threadpool(_cuerpo_r, user=user, data=data)",
    )
    assert _infracciones(fn) == []


def test_el_verificador_marca_hashing_y_correo_en_el_loop():
    malas = _infracciones(_con_form("h = hash_nip('1234')", "StudentMail.send(1)"))
    assert any("hash_nip" in m for m in malas)
    assert any("StudentMail.send" in m for m in malas)


def test_el_verificador_exige_terminar_delegando_al_threadpool():
    fn = _fn(
        "async def r(request):",
        "    form = await request.form()",
        "    return Response()",
    )
    assert any("run_in_threadpool" in m for m in _infracciones(fn))


def test_el_verificador_acepta_la_forma_canonica_y_las_guardas():
    fn = _fn(
        "async def r(request):",
        "    bloqueo = _mode_block(_OFFICIAL)",
        "    if bloqueo is not None:",
        "        return bloqueo",
        "    if not printing_enabled():",
        "        return Response(status_code=404)",
        "    tamano = _declared_body_size(request.headers)",
        "    if tamano is None:",
        "        return Response(status_code=411, headers={'X-Tt-Error': _hdr('x')})",
        "    form = dict(await request.form())",
        "    return await run_in_threadpool(_cuerpo_r, request=request, form=form)",
    )
    assert _infracciones(fn) == []


def test_el_verificador_acepta_la_lectura_del_archivo():
    fn = _fn(
        "async def r(archivo):",
        "    raw = await archivo.read()",
        "    return await run_in_threadpool(_cuerpo_r, raw=raw)",
    )
    assert _infracciones(fn) == []


def test_un_servicio_dentro_de_run_in_threadpool_como_referencia_no_es_una_llamada_en_el_loop():
    fn = _fn(
        "async def r(request):",
        "    raw = await request.body()",
        "    previo = await run_in_threadpool(DocumentService.validate, raw=raw)",
        "    return await run_in_threadpool(_cuerpo_r, previo=previo)",
    )
    assert _infracciones(fn) == []
