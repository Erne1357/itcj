"""Primitivas de contexto de petición: ids de correlación W3C.

Trace/span ids con forma W3C (`trace_id` 32 hex, `span_id` 16 hex, siempre
minúsculas) para que sean válidos en Tempo desde el día uno sin tener que
migrar nada cuando entre OpenTelemetry (Fase 7 del plan de instrumentación).

Por qué ContextVars y no un simple `threading.local` ni una variable global:
uvicorn corre cada petición HTTP en su propia `asyncio.Task`, y una
`asyncio.Task` SÍ copia el `contextvars.Context` del código que la crea (a
diferencia de un `threading.Thread` nativo, que no hereda nada). Eso da
aislamiento gratis entre peticiones concurrentes en el caso común (endpoints
async), y dos fronteras que SÍ hay que cruzar a mano quedan cubiertas por
`snapshot()`/`restore()`: un hilo nativo (el threadpool de anyio que ejecuta
los endpoints `def` síncronos, o `asyncio.to_thread`) y cualquier callback que
Python programe fuera de la Task original.

R4 (progress.md): `bind()`/`reset()` son explícitos a propósito — el
middleware (Task 3) NO hace `reset()` en el camino de una excepción no
controlada, para que el `logger.exception` de `ServerErrorMiddleware` (que
corre POR FUERA de este middleware) siga viendo el `request_id` de la
petición que falló.
"""
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# ContextVars
# ---------------------------------------------------------------------------
# `_scope` guarda una REFERENCIA al dict `scope` de ASGI de la petición en
# curso (no una copia): el filtro de logs (Task 4) lo lee en diferido, cuando
# el `LogRecord` ya se está formateando, para sacar `route`/`user_id` sin que
# el middleware tenga que pasárselos a cada `logger.info()` de la app.
_trace_id: ContextVar[str] = ContextVar("itcj_trace_id")
_span_id: ContextVar[str] = ContextVar("itcj_span_id")
_request_id: ContextVar[str] = ContextVar("itcj_request_id")
_scope: ContextVar[dict] = ContextVar("itcj_scope")

_VARS = {
    "trace_id": _trace_id,
    "span_id": _span_id,
    "request_id": _request_id,
    "scope": _scope,
}

# ---------------------------------------------------------------------------
# OpenTelemetry: import resuelto UNA vez al cargar el módulo
# ---------------------------------------------------------------------------
# TRAMPA MEDIDA (review de Task 2, ronda 1): Python cachea un import que
# CARGA en `sys.modules`, pero NO cachea uno que falla — cada intento repite
# los path finders (un `stat` por entrada de `sys.path`) y toma el import
# lock. Medido en el contenedor de dev intentando `from opentelemetry import
# trace` en cada llamada: 793.85 us/llamada contra 0.030 us/llamada de
# `current_request_id()` (~26 000x). `current_trace_id()` está en el camino
# caliente de la Fase 1b/1c: el middleware de Task 3 lo toca en cada
# petición y el filtro de logging de Task 4 en cada línea de log (incluso
# desde hilos del threadpool de anyio, compitiendo por el import lock entre
# ellos). Por eso el intento se hace una sola vez aquí, al importar este
# módulo — el resultado (instalado o no) no cambia en caliente dentro de un
# mismo proceso — y los tests que ejercitan la rama OTel parchean este
# atributo de módulo (`context._otel_trace`) en vez de `sys.modules`: una vez
# que el import ya corrió al cargar el módulo, tocar `sys.modules` después no
# tiene ningún efecto sobre `current_trace_id()`.
try:
    from opentelemetry import trace as _otel_trace
except ImportError:
    _otel_trace = None


def new_ids() -> tuple[str, str]:
    """Genera un par `(trace_id, span_id)` nuevo con forma W3C.

    `secrets.token_hex` ya produce hex en minúsculas del largo exacto que
    pide el estándar (16 bytes = 32 hex para trace, 8 bytes = 16 hex para
    span); no hace falta la estructura de UUID, solo aleatoriedad
    criptográfica del tamaño correcto.
    """
    return secrets.token_hex(16), secrets.token_hex(8)


# ---------------------------------------------------------------------------
# traceparent (W3C Trace Context) entrante
# ---------------------------------------------------------------------------
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


def parse_traceparent(value: str | None) -> tuple[str, str] | None:
    """Parsea un header `traceparent` entrante.

    Regresa `(trace_id, parent_span_id)` si es válido, o `None` si no —
    nunca lanza. `None` cubre: valor vacío, forma distinta a
    `00-<32hex>-<16hex>-<2hex>`, cualquier campo con caracteres fuera de
    `[0-9a-f]` (mayúsculas incluidas: W3C exige minúsculas) y trace_id/span_id
    "todo ceros" (reservados por el spec como inválidos).

    Solo se acepta versión `"00"`: versiones futuras del spec pueden traer
    campos adicionales que este regex no contempla, y aceptar una versión
    que no se sabe interpretar completa es peor que regenerar el id.
    """
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value)
    if match is None:
        return None
    if match.group("version") != "00":
        return None
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id


# ---------------------------------------------------------------------------
# bind/reset
# ---------------------------------------------------------------------------

def bind(**kwargs) -> dict:
    """Fija los ContextVars indicados y regresa los tokens para deshacerlos.

    Solo toca las claves recibidas: `bind(trace_id=x)` no pisa `span_id`,
    `request_id` ni `scope` que ya estuvieran fijados en este contexto.
    """
    tokens = {}
    for name, value in kwargs.items():
        var = _VARS.get(name)
        if var is None:
            raise TypeError(f"bind() no reconoce el campo de contexto {name!r}")
        tokens[name] = var.set(value)
    return tokens


def reset(tokens: dict) -> None:
    """Deshace exactamente los ContextVars que fijó el `bind()` que produjo
    `tokens` — nunca los que el contexto ya traía antes de ese `bind()`."""
    for name, token in tokens.items():
        _VARS[name].reset(token)


# ---------------------------------------------------------------------------
# Lectores
# ---------------------------------------------------------------------------

def current_trace_id() -> str:
    """Trace id activo.

    Prefiere el span de OpenTelemetry si el SDK está instalado y hay un span
    válido en curso — esto es lo que hace que la Fase 7 (OTel real) sea un
    drop-in: el logging y las métricas ya leen de aquí sin cambiar una línea
    cuando el SDK entre. Hoy el SDK no está instalado (no está en
    requirements.txt), así que `_otel_trace` es `None` (resuelto una sola vez
    al importar el módulo, ver arriba) y siempre cae al ContextVar que puebla
    `bind()`.
    """
    if _otel_trace is not None:
        span_context = _otel_trace.get_current_span().get_span_context()
        if span_context.is_valid:
            return format(span_context.trace_id, "032x")

    return _trace_id.get(None) or ""


def current_span_id() -> str:
    return _span_id.get(None) or ""


def current_request_id() -> str:
    return _request_id.get(None) or ""


def current_scope() -> dict | None:
    """El dict `scope` de ASGI de la petición en curso, o `None` fuera de
    una petición (p. ej. un log emitido desde un task de arranque)."""
    return _scope.get(None)


# ---------------------------------------------------------------------------
# snapshot/restore — cruzar fronteras que NO propagan ContextVars solas
# ---------------------------------------------------------------------------

def snapshot() -> dict:
    """Copia serializable a JSON de los ids activos.

    Deliberadamente NO incluye `scope`: el dict de ASGI trae objetos no
    serializables (`receive`/`send`/la app) y lo único que hace falta llevar
    a un hilo o tarea nuevos son los ids, no el scope completo.
    """
    return {
        "trace_id": _trace_id.get(None),
        "span_id": _span_id.get(None),
        "request_id": _request_id.get(None),
    }


@contextmanager
def restore(snap: dict | None):
    """Reinstala un `snapshot()` en el contexto/hilo actual.

    Para las fronteras que NO propagan ContextVars por sí solas: un
    `threading.Thread` nativo no hereda el contexto del hilo que lo crea (a
    diferencia de una `asyncio.Task`, que sí copia el `Context` al nacer).

    Tolera `None` y snapshots incompletos: los campos ausentes o en `None`
    simplemente no se fijan — no se sobreescribe con vacío lo que ya hubiera
    en este contexto.
    """
    snap = snap or {}
    to_bind = {
        name: value
        for name, value in snap.items()
        if name in _VARS and value is not None
    }
    tokens = bind(**to_bind)
    try:
        yield
    finally:
        reset(tokens)
