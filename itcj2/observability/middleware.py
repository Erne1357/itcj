"""Middleware ASGI puro: contexto de petición, cronómetro, métricas RED y una
línea por petición.

Por qué ASGI puro y no `BaseHTTPMiddleware` (plan §9.1). NO es por la
creencia de que un `ContextVar` puesto en `dispatch` no llega al endpoint (sí
llega, medido), sino porque:
1. Coste: `BaseHTTPMiddleware` añade tareas y streams de anyio por petición, y
   `JWTMiddleware` ya paga uno.
2. Solo ve un `Response` ya construido: no puede leer el `status` de
   `http.response.start` ni añadir una cabecera sin materializar el cuerpo,
   y aquí hacen falta las dos cosas sin romper el streaming de los exports.
3. Que el contexto propague hoy a través de él no es un contrato (lo fija
   `test_context_propagation.py`).

Se registra el ÚLTIMO en `setup_middleware()`, así que es el más externo DE
LOS DE USUARIO. Por encima sigue `ServerErrorMiddleware` (plan §9.15): ante
una excepción no controlada el 500 lo emite esa capa y el `send` envuelto no
lo ve nunca. De ahí el `except BaseException` explícito.
"""
import logging
import secrets
from time import perf_counter

from starlette.datastructures import MutableHeaders

from itcj2.observability.context import bind, new_ids, parse_traceparent, reset
from itcj2.observability.metrics import (
    HTTP_EXCEPTIONS,
    HTTP_IN_FLIGHT,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
)
from itcj2.observability.route import UNMATCHED, app_key_from_route, normalize_route

# Nombre fijo y no `__name__`: es el contrato con la configuración de logs
# (nivel y handler propios) y con las consultas de Loki sobre la línea-resumen.
access_logger = logging.getLogger("itcj2.access")

# El healthcheck de Docker pega a /ready cada 5 s en tres contenedores y
# Prometheus a /metrics en cada scrape: medirlos solo sería ruido en Loki y
# series en Prometheus.
SKIP_PATHS = frozenset({"/health", "/ready", "/metrics"})

_TRACEPARENT = b"traceparent"

# El método es entrada del cliente: el servidor HTTP acepta decenas (PROPFIND,
# PURGE, TRACE…) o cualquier token, y cada uno sería una etiqueta nueva. En
# las métricas va tal cual solo si es uno de estos; si no, "OTHER".
METRIC_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _metric_route_method(route: str, method: str, status: int) -> tuple[str, str]:
    """`route` y `method` como etiquetas de métrica (la línea-resumen no).

    Un 405 conserva la plantilla real (match parcial de Starlette) y llega
    antes de la autenticación: un HEAD a cada ruta GET (FastAPI no añade HEAD)
    o un barrido de métodos abriría método × plantilla × (1 + 14 del
    histograma) series que el presupuesto de §6 no cuenta, y un cliente
    anónimo tumbaría el `mem_limit` de Prometheus, que es de TODO el stack.
    En las métricas va a `"__unmatched__"`, como un 404; en Loki la línea
    conserva la ruta real para investigar.
    """
    if status == 405:
        route = UNMATCHED
    return route, method if method in METRIC_METHODS else "OTHER"


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1")
    return None


def user_id_from_scope(scope: dict) -> str:
    """`sub` del JWT como cadena, o `""` si la petición es anónima.

    `JWTMiddleware` corre POR DENTRO de este middleware, pero escribe
    `request.state.current_user` en `scope["state"]`, que es el MISMO dict que
    este middleware tiene en la mano: por eso se lee después de la petición.
    Público porque el filtro de logs (`logging_config`) lo lee igual, en
    diferido, para las líneas emitidas dentro del endpoint.
    """
    current_user = (scope.get("state") or {}).get("current_user")
    if not isinstance(current_user, dict):
        return ""
    sub = current_user.get("sub")
    return "" if sub is None else str(sub)


def _log_summary(method, route, app, status, duration, user_id, exc_type) -> None:
    duration_ms = round(duration * 1000, 3)
    extra = {
        "method": method,
        "route": route,
        "app": app,
        "status": status,
        "duration_ms": duration_ms,
        "user_id": user_id,
    }
    if exc_type is not None:
        extra["exc_type"] = exc_type
    access_logger.info(
        "%s %s %s %.1fms", method, route, status, duration_ms, extra=extra
    )


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        trace_id, span_id = new_ids()
        incoming = parse_traceparent(_header(scope, _TRACEPARENT))
        if incoming is not None:
            # Del traceparent solo se hereda la traza: su span es el del
            # LLAMANTE (el padre), esta petición abre uno propio.
            trace_id = incoming[0]
        # Siempre generado, nunca el X-Request-ID entrante: un id elegido por
        # el cliente podría hacerse pasar por el de otra petición en los logs.
        request_id = secrets.token_hex(16)
        tokens = bind(
            trace_id=trace_id, span_id=span_id, request_id=request_id, scope=scope
        )

        status = None
        exc_type = None

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                # R20: ASGI permite omitir "headers"; MutableHeaders lo exige.
                message.setdefault("headers", [])
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        # La ruta plantillada no existe hasta que Starlette enruta, POR DENTRO:
        # el in-flight se etiqueta con la app del path crudo. Mismo conjunto
        # cerrado de valores (app_key_from_route solo devuelve claves conocidas
        # u "otro"), así que no abre cardinalidad; la diferencia es que un 404
        # bajo /api/help-desk/ cuenta aquí como helpdesk y en el contador
        # como "otro". Se guarda el hijo para decrementar el MISMO que se sumó.
        in_flight = HTTP_IN_FLIGHT.labels(app=app_key_from_route(scope["path"]))
        in_flight.inc()
        start = perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            # 500 aunque ya hubiera salido un http.response.start: la
            # respuesta quedó cortada, para el cliente también es un fallo.
            status = 500
            exc_type = type(exc).__name__
            # Re-lanzar SIEMPRE: el 500 (y el logger.exception del handler
            # global) lo sigue emitiendo ServerErrorMiddleware, por fuera.
            raise
        finally:
            duration = perf_counter() - start
            in_flight.dec()
            if status is None:
                # R19: la app terminó sin http.response.start y sin lanzar.
                # Uvicorn responde entonces con su propio 500 ("ASGI callable
                # returned without starting response"): eso vio el cliente.
                status = 500
            # Starlette rellena scope["route"] EN SITIO al enrutar, así que
            # aquí ya está, también cuando el endpoint reventó.
            route = normalize_route(scope)
            app = app_key_from_route(route)
            method = scope["method"]
            metric_route, metric_method = _metric_route_method(route, method, status)
            # De la ruta de la MÉTRICA: un 405 cuenta como "otro", igual que
            # un 404 ("__unmatched__" -> "otro" es el contrato).
            metric_app = app_key_from_route(metric_route)
            HTTP_REQUESTS.labels(
                app=metric_app, method=metric_method, route=metric_route,
                status=str(status),
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                app=metric_app, method=metric_method, route=metric_route
            ).observe(duration)
            if exc_type is not None:
                HTTP_EXCEPTIONS.labels(
                    app=metric_app, route=metric_route, exc_type=exc_type
                ).inc()
            _log_summary(
                method, route, app, status, duration,
                user_id_from_scope(scope), exc_type,
            )
            # R4: sin reset en el camino de excepción, para que el
            # logger.exception del handler global (ServerErrorMiddleware, por
            # fuera) y el log de error de uvicorn lleven el request_id de la
            # petición que falló. Uvicorn corre cada petición en su propia
            # Task, así que el contexto no se hereda a la siguiente.
            if exc_type is None:
                reset(tokens)
