"""Plantillado de ruta y `app_key` a partir del `scope` de ASGI.

TRAMPA MEDIDA (reconocimiento 2026-09-21, ver
`.superpowers/sdd/2026-09-21-obs-f0-f3/ref/enum_routes6.py`, validado 25/25
contra peticiones reales de la app): en fastapi 0.141 `scope["route"].path`
es LOCAL al router hoja donde se declaró el endpoint. Antes, `include_router`
"aplanaba" los routers incluidos: copiaba cada `Route` al router destino con
el prefijo completo ya horneado en `.path`. Ahora deja un nodo interno
`fastapi.routing._IncludedRouter` que envuelve al router original tal cual, y
cada `Route` conserva solo el prefijo que tenía HORNEADO cuando se agregó a
SU router (el de nivel más hoja), sin los prefijos de ningún ancestro. Por
ejemplo, un endpoint declarado como `@router.get("/{ticket_id}")` en un
router sin prefijo propio, incluido primero con `prefix="/tickets"` en el
router de la app y ese a su vez con `prefix="/api/help-desk/v2"` en la app,
dejaría `scope["route"].path == "/{ticket_id}"` — sin rastro de
`/api/help-desk/v2/tickets`.

La solución es un mapa `id(route) -> plantilla completa`, construido
recorriendo recursivamente `app.routes` y reconstruyendo el prefijo completo
en cada `_IncludedRouter` (ver `_walk`). El mapa se arma una vez por app y se
cachea; `normalize_route()` solo hace el lookup.
"""
import logging
import weakref

logger = logging.getLogger("itcj2.observability")

UNMATCHED = "__unmatched__"


class _RootRouter:
    """Raíz sintética para arrancar `_walk` con `prefix=""`.

    `app.routes` es la lista de routers/rutas de nivel top montados
    directamente en la app (equivalente a `app.router.routes`); no hay un
    "router dueño" real que los contenga con un `.prefix` propio, así que se
    inventa uno vacío para no tener que ramificar `_walk` en un caso especial
    para el primer nivel.
    """

    prefix = ""


def _walk(routes, ancestor_prefix, owning_router, sink) -> None:
    """Recorre `routes` recursivamente y llama `sink(route_obj, full_path)`
    por cada `Route`/`APIRoute` y `WebSocketRoute`/`APIWebSocketRoute` real
    que encuentra (`APIRoute`/`APIWebSocketRoute` son subclases de
    `Route`/`WebSocketRoute`: el `isinstance` de abajo ya cubre ambas sin
    necesidad de importar las clases de fastapi por separado).

    `ancestor_prefix` es el prefijo acumulado por TODO lo que está afuera de
    `owning_router` (no incluye el `.prefix` propio de `owning_router`: ese
    ya está horneado en el `.path` de las rutas declaradas directo sobre él).

    `owning_router` es el `APIRouter` dueño de `routes`. Hace falta su
    `.prefix` para poder aislar, en un `_IncludedRouter` anidado, el
    `prefix=` EXPLÍCITO que se le pasó a ESE `include_router` en particular:
    fastapi deja `include_context.prefix = owning_router.prefix + ese
    prefix explícito` (no la ruta absoluta ya resuelta contra todos los
    ancestros), así que hay que restarle `owning_router.prefix` para
    recuperar solo la parte explícita antes de sumarla al `ancestor_prefix`
    real.
    """
    from starlette.routing import Mount, Route, WebSocketRoute

    for entry in routes:
        kind = type(entry).__name__
        if kind == "_IncludedRouter":
            sub_router = entry.original_router
            include_ctx = entry.include_context
            ctx_prefix = getattr(include_ctx, "prefix", "") or ""
            owner_prefix = getattr(owning_router, "prefix", "") or ""
            if ctx_prefix.startswith(owner_prefix):
                explicit_prefix = ctx_prefix[len(owner_prefix):]
            else:
                # No debería pasar según el comportamiento verificado de
                # fastapi 0.141 (ver docstring del módulo), pero mejor no
                # corromper el prefijo en silencio si algún día deja de
                # cumplirse: se usa el prefijo completo tal cual, que en el
                # peor caso duplica un tramo en vez de perderlo.
                explicit_prefix = ctx_prefix
            _walk(
                sub_router.routes,
                ancestor_prefix + owner_prefix + explicit_prefix,
                sub_router,
                sink,
            )
        elif isinstance(entry, Mount):
            full_path = ancestor_prefix + entry.path
            sub_routes = getattr(entry.app, "routes", None)
            if sub_routes:
                _walk(sub_routes, full_path, _RootRouter(), sink)
        elif isinstance(entry, (Route, WebSocketRoute)):
            sink(entry, ancestor_prefix + entry.path)
        # Cualquier otro tipo de nodo (kinds futuros de starlette) se
        # ignora: no aporta una plantilla instrumentable.


def build_route_map(app) -> dict:
    """Recorre `app.routes` y arma `{id(route): plantilla_completa}`.

    Incluye `APIRoute`/`Route` y `APIWebSocketRoute`/`WebSocketRoute` (para
    completitud del mapa — el middleware de instrumentación, Task 3, no
    instrumenta websockets, pero el mapa no debe tener huecos silenciosos
    para las rutas que sí existen).
    """
    route_map: dict = {}

    def _collect(route_obj, full_path):
        route_map[id(route_obj)] = full_path

    _walk(app.routes, "", _RootRouter(), _collect)
    return route_map


def _route_method_pairs(app) -> list:
    """SOLO para el guardián de unicidad de
    `tests/fastapi/observability/test_route_template.py`: enumera
    `(método, plantilla completa)` por cada `Route` real de `app`.

    Se excluye `HEAD`: fastapi lo agrega automáticamente a cada ruta `GET`,
    y contarlo duplicaría cada ruta GET sin que eso sea un colapso real del
    walker (ver `ref/enum_routes6.py`, que hace el mismo descarte).
    """
    from starlette.routing import Route

    pairs = []

    def _collect(route_obj, full_path):
        if not isinstance(route_obj, Route):
            return
        for method in route_obj.methods or ():
            if method == "HEAD":
                continue
            pairs.append((method, full_path))

    _walk(app.routes, "", _RootRouter(), _collect)
    return pairs


# ---------------------------------------------------------------------------
# Mapa por app: perezoso, cacheado, una vez por app
# ---------------------------------------------------------------------------
# `WeakKeyDictionary` (no `id(app) -> mapa`): si se usara `id(app)` como
# llave, un `app` viejo recolectado por el GC podría cederle su id a un
# objeto nuevo (CPython reutiliza ids) y esa app nueva heredaría en silencio
# el mapa de rutas de otra completamente distinta. Con la app como llave
# débil, la entrada se libera sola cuando la app muere y nunca hay colisión.
_route_maps: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

# Warnings de "ruta no encontrada en el mapa" solo una vez por route id, para
# no inundar el log en producción bajo tráfico real contra la misma ruta rota.
_warned_route_ids: set = set()


def _get_route_map(app) -> dict:
    route_map = _route_maps.get(app)
    if route_map is None:
        # Perezoso, cacheado. Si dos peticiones concurrentes llegan antes de
        # que exista la entrada, cada una construye su propio mapa y una
        # pisa a la otra en el WeakKeyDictionary: inocuo, porque ambos mapas
        # salen de recorrer el mismo `app.routes` y son idénticos.
        route_map = build_route_map(app)
        _route_maps[app] = route_map
    return route_map


def normalize_route(scope) -> str:
    """Plantilla completa de la ruta que sirvió `scope`, o `"__unmatched__"`.

    `scope.get("route")`, nunca `scope["route"]`: en un 404 esa clave no
    existe. Un 405 (método no permitido) sí deja el `Route` matcheado en el
    scope (match parcial de Starlette), así que produce la plantilla real,
    no `"__unmatched__"`.
    """
    route = scope.get("route")
    if route is None:
        return UNMATCHED

    app = scope.get("app")
    route_map = _get_route_map(app) if app is not None else None
    template = route_map.get(id(route)) if route_map is not None else None
    if template is not None:
        return template

    # Fallo VISIBLE, no silencioso: si esto se dispara, `_walk` no reconoció
    # esta ruta (p. ej. un cambio interno de fastapi/starlette en cómo
    # cuelga los routers de `app.routes`). El test de unicidad de
    # `test_route_template.py` es el guardián de que esto no pase en la app
    # real; si algún día SÍ pasa, mejor un warning ruidoso una vez que una
    # métrica con la plantilla cruda equivocada coleccionándose en silencio.
    route_id = id(route)
    if route_id not in _warned_route_ids:
        _warned_route_ids.add(route_id)
        logger.warning(
            "normalize_route: la ruta %r (id=%s) no está en el mapa de "
            "rutas de la app; usando route.path crudo como plantilla "
            "(ver docstring de itcj2.observability.route)",
            getattr(route, "path", None),
            route_id,
        )
    return getattr(route, "path", None) or UNMATCHED


# ---------------------------------------------------------------------------
# app_key_from_route()
# ---------------------------------------------------------------------------
_ALIAS = {
    # Con guion en la URL, sin guion en la app_key (recon 2026-09-21: 210
    # pares de /api/help-desk + 55 de /help-desk = 265 en total).
    "help-desk": "helpdesk",
    # Páginas del core (login, dashboard, perfil, móvil). "itcj" no es una
    # app_key válida por sí sola (recon 2026-09-21: 23 pares).
    "itcj": "core",
}

_KEYS = {
    "helpdesk",
    "agendatec",
    "maint",
    "titulatec",
    "vistetec",
    "warehouse",
    "directory",
    # R9 (progress.md): la app SGC de Calidad aún no está registrada en esta
    # rama (no aparece en itcj2/routers.py), pero la clave ya se reconoce
    # aquí para no tener que volver a tocar este archivo el día que se
    # registre — una clave dormida, no un bug.
    "adhoc",
    "core",
}


def app_key_from_route(path: str) -> str:
    """Deriva la `app_key` de una plantilla de ruta.

    Reconoce las dos formas en que este proyecto expone rutas: `/api/<seg>/…`
    (API REST) y `/<seg>/…` (páginas HTML). Sin alias ni pertenencia a
    `_KEYS`, cae a `"otro"` — el descarte es a propósito y no defensivo por
    gusto: sin él, una app nueva que alguien registre en `routers.py` sin
    actualizar esta tabla se colaría en las métricas con una clave
    inventada; con él, aparece como `"otro"` en el tablero y se nota.
    """
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "otro"

    first = segments[0]
    if first == "api":
        if len(segments) < 2:
            return "otro"
        candidate = segments[1]
    else:
        candidate = first

    candidate = _ALIAS.get(candidate, candidate)
    return candidate if candidate in _KEYS else "otro"
