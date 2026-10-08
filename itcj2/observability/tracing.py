"""Trazas OpenTelemetry (plan Fase 7): OTLP gRPC a Alloy -> Tempo.

Apagado por defecto. Solo `OTEL_ENABLED == "1"` lo enciende; con cualquier
otro valor `setup_tracing()` regresa `None` sin importar el SDK, ningún span se
abre y todo se comporta exactamente como antes de esta fase. Rollback: volver
a `0` y redesplegar, sin tocar código.

DECISIÓN CENTRAL — un solo trace id en todo el sistema
------------------------------------------------------
El botón Loki -> Tempo de Grafana toma el `trace_id` de la línea JSON y lo
busca en Tempo. Si el id de los logs y el del span difieren, el botón abre una
traza vacía, sin ningún error. Por eso, con OTel activo, el span OTel es la
FUENTE de los ids y el contexto propio (`context.py`) es su copia:

1. Cada frontera abre su span y LIGA sus ids al contexto propio con el mismo
   `bind()` de siempre, en lugar de acuñarlos con `new_ids()`:
   - HTTP (`middleware.py`): span servidor, hijo del `traceparent` entrante si
     viene (validado con el mismo `parse_traceparent`, así el id heredado es
     el mismo con OTel encendido o apagado).
   - Socket.IO (`sockets/instrumentation.py`): span raíz por evento.
   - Celery: el span lo abre `CeleryInstrumentor` en su `task_prerun`, y el
     receptor propio de `celery_hooks` se reconecta para correr DESPUÉS
     (`run_after_otel_prerun`) y ligar los ids de ese span. Celery llama a los
     receptores en orden de conexión, y los hooks propios se conectan al
     importar `celery_app`, antes que el instrumentor: sin reordenar, la tarea
     ligaría una raíz propia distinta de la de Tempo (y el `trace_id` del
     payload de `task_events`, que OTel no conoce, también sería otro).
2. Todo lo que ya lee del contexto propio (el filtro de logs, `snapshot()`
   para Celery y `task_events`, `X-Request-ID`) sigue igual y ya ve los ids
   del span. `current_trace_id()` además preferiría el span activo por su
   cuenta (lo hace desde la Fase 1), así que dentro de un span hijo (una
   consulta SQL) el `trace_id` sigue siendo el mismo.
3. Apagado, `start_span()` regresa `None` y cada frontera cae a `new_ids()`
   como siempre: la rama apagada no cambia ni una línea de su comportamiento.

Qué NO se instrumenta, a propósito: FastAPI (`-instrumentation-fastapi`
abriría un segundo span servidor sin la regla `__unmatched__`) y logging
(`-instrumentation-logging`: el filtro propio ya pone los ids).

Privacidad: atributos HTTP solo `http.request.method`, `http.route` (la
plantilla) y `http.response.status_code`; `url.path` SOLO cuando la ruta es
`__unmatched__` (un 404 no tiene plantilla y es lo único que permite
investigarlo, igual que el campo `path` de la línea-resumen), acotado y sin
query string. Una ruta matcheada no lleva la cruda: sus parámetros pueden ser
un número de control o un correo, y la plantilla ya dice todo lo útil. Nunca
`user_id`. Redis manda los comandos sin valores (`SET ? ?`, lo sanea el propio
instrumentor); requests/httpx mandan la URL, y las llamadas salientes de hoy
(MS Graph, la API de fútbol) llevan sus credenciales en cabeceras, que no se
registran.

Procesos: `uvicorn --workers 4` lanza procesos nuevos (spawn), y cada uno
corre `create_app()` -> `setup_tracing()`: un provider por worker, bien. En
Celery prefork, el hilo del `BatchSpanProcessor` y el canal gRPC NO sobreviven
al `fork`: se inicializa en `worker_process_init` (cada hijo), nunca al
importar ni en el padre. El beat no se instrumenta: solo encola, y la tarea
abre su raíz en el worker.

Fail-safe: si Alloy no responde, el exportador reintenta y descarta (la cola
del batch es acotada); nada de este módulo lanza hacia una petición, un evento
o una tarea. `shutdown_tracing()` en el `lifespan` y en
`worker_process_shutdown` vacía el batch al apagar.

Este módulo está en la cadena de imports de Celery: solo `logging`/`os` al
importar (nada de `prometheus_client`, ni del SDK).
"""
import logging
import os
from typing import Any, NamedTuple

logger = logging.getLogger("itcj2.observability.tracing")

ENABLED_ENV = "OTEL_ENABLED"
ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
DEFAULT_ENDPOINT = "http://alloy:4317"
SERVICE_NAME = "itcj"
DEPLOYMENT_ENVIRONMENT = "prod"
INSTRUMENTATION_SCOPE = "itcj2"

_provider = None
_tracer = None
# `(nombre, instrumentor)` de lo que SÍ quedó instrumentado.
_instrumentors: list = []


class ActiveSpan(NamedTuple):
    """Un span abierto y ACTIVO en el contexto OTel actual (`token` lo
    desactiva), con sus ids ya en la forma W3C del contexto propio."""
    span: Any
    token: Any
    trace_id: str
    span_id: str


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "") == "1"


def instrumented_libraries() -> tuple[str, ...]:
    """Las bibliotecas instrumentadas en este proceso (vacío si apagado)."""
    return tuple(name for name, _ in _instrumentors)


def otlp_endpoint() -> str:
    return os.environ.get(ENDPOINT_ENV) or DEFAULT_ENDPOINT


def build_provider(role: str | None = None):
    """El `TracerProvider` de producción: recurso, `ALWAYS_ON` y el batch
    hacia Alloy. El muestreo NO va aquí sino en Alloy (tail sampling): un
    ratio fijo en la app perdería justo la petición lenta de las 3 a. m."""
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    role = role or os.environ.get("APP_ROLE") or "all"
    # Los workers de Celery no tienen color: su `CELERY_HOSTNAME` (worker /
    # reports) es lo que los distingue entre sí.
    namespace = (
        os.environ.get("INSTANCE_COLOR") or os.environ.get("CELERY_HOSTNAME") or role
    )
    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.namespace": namespace,
        "deployment.environment.name": DEPLOYMENT_ENVIRONMENT,
        "itcj.app_role": role,
    })
    provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint(), insecure=True))
    )
    return provider


def setup_tracing(provider=None, *, role: str | None = None):
    """Enciende el tracing en este proceso si `OTEL_ENABLED=1`.

    Regresa el provider activo, o `None` si está apagado o falló (la app sigue
    sin trazas). Idempotente: una segunda llamada regresa el mismo provider
    sin reinstrumentar nada.

    `provider` es para los tests: uno inyectado NO se fija como provider
    global de OpenTelemetry (que solo se puede fijar una vez por proceso);
    los instrumentors lo reciben explícito.
    """
    global _provider, _tracer
    if not enabled():
        return None
    if _provider is not None:
        return _provider
    try:
        if provider is None:
            provider = build_provider(role)
            from opentelemetry import trace

            trace.set_tracer_provider(provider)
        tracer = provider.get_tracer(INSTRUMENTATION_SCOPE)
    except Exception:
        logger.exception("tracing: no se pudo iniciar; la app sigue sin trazas")
        return None
    _provider, _tracer = provider, tracer
    _instrument_libraries(provider)
    logger.info(
        "tracing: OpenTelemetry activo (OTLP %s; instrumentado: %s)",
        otlp_endpoint(), ", ".join(instrumented_libraries()) or "nada",
    )
    return provider


def shutdown_tracing() -> None:
    """Vacía el batch y deshace los instrumentors. Nunca lanza."""
    global _provider, _tracer
    provider = _provider
    if provider is None:
        return
    _provider = _tracer = None
    while _instrumentors:
        _, instrumentor = _instrumentors.pop()
        try:
            instrumentor.uninstrument()
        except Exception:
            logger.warning("tracing: fallo al desinstrumentar %r", instrumentor, exc_info=True)
    try:
        provider.shutdown()
    except Exception:
        logger.warning("tracing: fallo al vaciar el batch de spans", exc_info=True)


# ---------------------------------------------------------------------------
# Instrumentors: cinco llamadas que cubren todo el código sin tocarlo
# ---------------------------------------------------------------------------

def _sqlalchemy(provider):
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from itcj2.database import engine

    instrumentor = SQLAlchemyInstrumentor()
    # `skip_dep_check`: la 0.66b1 (la última) declara `sqlalchemy < 2.1` y con
    # la 2.1.x instalada NO instrumenta nada — solo deja un ERROR en el log y
    # la traza sale sin un solo SELECT. Lo que usa (eventos públicos del
    # engine: before/after_cursor_execute, handle_error, connect, checkout...)
    # no cambió en 2.1; `test_la_consulta_a_bd_es_un_span_hijo_de_la_misma_traza`
    # lo comprueba contra la versión instalada. Quitarlo cuando la contrib
    # declare 2.1.
    instrumentor.instrument(engine=engine, tracer_provider=provider, skip_dep_check=True)
    return instrumentor


def _redis(provider):
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    instrumentor = RedisInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    return instrumentor


def _requests(provider):
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    instrumentor = RequestsInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    return instrumentor


def _httpx(provider):
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    instrumentor = HTTPXClientInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    return instrumentor


def _celery(provider):
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    from itcj2.observability import celery_hooks

    instrumentor = CeleryInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    # Ver el docstring del módulo, punto 1: el receptor propio tiene que ver
    # el span que acaba de abrir el instrumentor.
    celery_hooks.run_after_otel_prerun()
    return instrumentor


_INSTRUMENTATIONS = (
    ("sqlalchemy", _sqlalchemy),
    ("redis", _redis),
    ("requests", _requests),
    ("httpx", _httpx),
    ("celery", _celery),
)


def _instrument_libraries(provider) -> None:
    # Uno por uno: si falla uno, los demás siguen (mejor trazas sin Redis que
    # ninguna traza).
    for name, instrument in _INSTRUMENTATIONS:
        try:
            _instrumentors.append((name, instrument(provider)))
        except Exception:
            logger.exception("tracing: no se pudo instrumentar %s; sigue sin esos spans", name)


# ---------------------------------------------------------------------------
# Spans de las fronteras propias (HTTP, Socket.IO)
# ---------------------------------------------------------------------------

def start_span(
    name: str,
    *,
    parent: tuple[str, str] | None = None,
    root: bool = False,
    server: bool = False,
) -> ActiveSpan | None:
    """Abre un span y lo deja ACTIVO en el contexto OTel actual.

    `parent` es un `(trace_id, span_id)` remoto ya validado (el del
    `traceparent`); `root=True` ignora cualquier span activo. Regresa `None`
    si el tracing está apagado o si algo falla: quien llama acuña sus ids como
    siempre. Nunca lanza.
    """
    tracer = _tracer
    if tracer is None:
        return None
    try:
        from opentelemetry import context as otel_context
        from opentelemetry import trace
        from opentelemetry.trace import (
            NonRecordingSpan,
            SpanContext,
            SpanKind,
            TraceFlags,
        )

        if parent is not None:
            # SAMPLED da igual con ALWAYS_ON; se pone para que un sampler
            # ParentBased futuro no descarte en silencio lo que pide el cliente.
            remote = SpanContext(
                trace_id=int(parent[0], 16),
                span_id=int(parent[1], 16),
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
            ctx = trace.set_span_in_context(NonRecordingSpan(remote), otel_context.Context())
        elif root:
            ctx = otel_context.Context()
        else:
            ctx = None
        kind = SpanKind.SERVER if server else SpanKind.INTERNAL
        span = tracer.start_span(name, context=ctx, kind=kind)
        token = otel_context.attach(trace.set_span_in_context(span))
        span_context = span.get_span_context()
        return ActiveSpan(
            span, token,
            format(span_context.trace_id, "032x"),
            format(span_context.span_id, "016x"),
        )
    except Exception:
        logger.warning("tracing: no se pudo abrir el span %r", name, exc_info=True)
        return None


def end_span(
    active: ActiveSpan | None,
    *,
    name: str | None = None,
    attributes: dict | None = None,
    error: bool = False,
    exception: BaseException | None = None,
    export: bool = True,
) -> None:
    """Cierra (y exporta) el span y lo desactiva. Nunca lanza.

    `export=False` lo desactiva SIN cerrarlo: el procesador solo exporta lo
    que termina, así que un span que no se cierra no llega a Tempo. Es para
    los intentos que la métrica tampoco cuenta (ver Socket.IO).
    """
    if active is None:
        return
    try:
        span = active.span
        if export:
            from opentelemetry.trace import Status, StatusCode

            if name:
                span.update_name(name)
            if attributes:
                span.set_attributes(attributes)
            if exception is not None:
                span.record_exception(exception)
            if error:
                span.set_status(Status(StatusCode.ERROR))
            span.end()
    except Exception:
        logger.warning("tracing: no se pudo cerrar el span", exc_info=True)
    finally:
        try:
            from opentelemetry import context as otel_context

            otel_context.detach(active.token)
        except Exception:
            logger.warning("tracing: no se pudo desactivar el span", exc_info=True)
