"""Logging del proceso: una línea JSON por registro, con el contexto de la petición.

Ningún módulo de la app cambia: sus `logger.info(f"…")` siguen igual y ganan
`trace_id`/`request_id`/`route`/`app`/`user_id` como campos hermanos del
mensaje, porque el filtro vive en el handler de root, no en cada logger.

Trampas que explican la forma de `configure_logging()`:

- Se llama en cada `create_app()`, y la suite de tests construye la app cientos
  de veces en un mismo proceso. Un `addHandler` a secas acumularía un handler
  por llamada (cada línea impresa cientos de veces al final de la corrida), y
  un `root.handlers = [...]` borraría los de pytest (`caplog`). Por eso el
  handler propio lleva una marca y solo se reemplaza ESE.
- Celery, al arrancar worker y beat, vacía `root.handlers`
  (`worker_hijack_root_logger`) salvo que haya un receptor en su señal
  `setup_logging`: la configuración de Celery va por ahí (ver
  `itcj2/celery_app.py`), nunca como llamada suelta al importar.
- uvicorn configura sus loggers (dictConfig) ANTES de importar la app y les
  cuelga su handler de texto con `propagate=False`: sin reemplazarlo, sus
  líneas saldrían en texto o duplicadas.
"""
import json
import logging
import sys
import threading
from datetime import datetime, timezone

from celery import current_task

from itcj2.config import get_settings
from itcj2.observability.context import (
    current_request_id,
    current_scope,
    current_span_id,
    current_trace_id,
    user_id_from_scope,
)
from itcj2.observability.route import app_key_from_route, normalize_route

# NO importar aquí `middleware` ni `metrics`: este módulo es lo único de la
# observabilidad que carga Celery (`itcj2/celery_app.py`), y esos dos arrastran
# `prometheus_client`. Con `PROMETHEUS_MULTIPROC_DIR` heredada del `.env`
# compartido, las métricas de módulo abrirían sus mmap en un directorio que
# nadie crea y Celery moriría al importar. Lo vigila
# `test_celery_arranca_aunque_herede_prometheus_multiproc_dir`.

# La línea-resumen por petición (la emite `ObservabilityMiddleware`). Nombre
# fijo: es el contrato con este módulo (nivel propio) y con Loki.
ACCESS_LOGGER_NAME = "itcj2.access"

# Atributo (no una subclase) para reconocer el handler propio: sobrevive a un
# `importlib.reload` de este módulo, que crearía una clase nueva y dejaría el
# handler viejo sin reconocer.
_OWN_MARK = "_itcj_observability"

# Siempre presentes en cada línea, vacíos sin petición: una consulta de Loki no
# tiene que distinguir "campo ausente" de "sin contexto". `celery_task_id` (R33)
# es el id de la tarea Celery en curso, el mismo que guarda
# `core_task_runs.celery_task_id`: une las líneas de un worker con su fila.
CONTEXT_FIELDS = (
    "trace_id", "span_id", "request_id", "user_id", "route", "app", "celery_task_id",
)

# Librerías que emiten INFO por cada llamada saliente o por cada archivo
# tocado (R6). `socketio.server`/`engineio.server` van aparte: con
# `logger=False` python-socketio les pone ERROR y les cuelga un StreamHandler
# de texto propio SOLO si al construir el servidor su nivel sigue en NOTSET; al
# fijarlo antes (create_app llama esto antes de importar itcj2.sockets) no lo
# cuelga, y sus ERROR salen una sola vez y en JSON, por root.
_QUIET_LOGGERS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "watchfiles": logging.WARNING,
    "msal": logging.WARNING,
    "socketio.server": logging.ERROR,
    "engineio.server": logging.ERROR,
}

_FORMATS = ("json", "text")

# Atributos que todo LogRecord trae de fábrica: lo que no esté aquí llegó por
# `extra=` y se emite tal cual. `message`/`asctime` los añade
# `Formatter.format()` si otro handler (caplog) formateó el registro antes.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", (), None))
) | {"message", "asctime"}

# uvicorn duplica cada mensaje con códigos ANSI en `color_message`.
_DROPPED_EXTRAS = frozenset({"color_message"})

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s rid=%(request_id)s %(message)s"


# ---------------------------------------------------------------------------
# Filtro: contexto de la petición en cada registro
# ---------------------------------------------------------------------------

# Candado por hilo contra la reentrada: la PRIMERA línea de log de una app
# arma su mapa de rutas (`normalize_route`), y armarlo puede emitir un warning
# (el mismo router incluido bajo dos prefijos) que vuelve a pasar por este
# filtro; sin el candado, cada vuelta reconstruiría el mapa y emitiría otro
# warning hasta un RecursionError.
_building = threading.local()


def _scope_fields() -> tuple[str, str, str]:
    """`(route, app, user_id)` leídos en diferido del `scope` ligado.

    En diferido para que una línea emitida DENTRO del endpoint ya traiga la
    plantilla (Starlette la deja en el scope al enrutar) y el usuario (el JWT
    lo deja en `scope["state"]`) sin que el middleware se los pase a nadie.
    """
    scope = current_scope()
    if scope is None or getattr(_building, "active", False):
        return "", "", ""
    _building.active = True
    try:
        route = normalize_route(scope)
        return route, app_key_from_route(route), user_id_from_scope(scope)
    except Exception:
        # Un filtro que lanza tumba el `logger.info()` de quien loguea: la
        # línea sale sin ruta antes que romper la petición.
        return "", "", ""
    finally:
        _building.active = False


def _celery_task_id() -> str:
    """Id de la tarea Celery que corre en este hilo, o `""` fuera de una.

    De la pila de tareas de Celery (`current_task`) y no de un ContextVar
    propio: la llena el propio Celery al ejecutar (también en eager), así que
    no depende de que los hooks de `celery_hooks` estén conectados. Fuera de
    una tarea (HTTP, sockets) la pila está vacía y cuesta una consulta a un
    thread-local. Una llamada directa (`task()`) no tiene id: `""`.
    """
    try:
        task = current_task._get_current_object()
        return (task.request.id or "") if task is not None else ""
    except Exception:
        # Un filtro que lanza tumba el `logger.info()` de quien loguea.
        return ""


class ContextFilter(logging.Filter):
    """Pone los campos de contexto como atributos de cada `LogRecord`.

    Los ids (`trace_id`, `span_id`, `request_id`, `celery_task_id`) salen
    SIEMPRE del contexto, aunque el registro traiga un `extra` con el mismo
    nombre: son la llave para unir líneas en Loki. Un id de negocio va con su
    propio nombre (agendatec: `extra={"agendatec_request_id": <id en BD>}`);
    ningún `extra` de la app puede usar esos nombres (lo vigila un test de
    `test_json_logging.py`), porque se perdería en silencio.
    `route`/`app`/`user_id` respetan el `extra` si viene: la línea-resumen los
    trae calculados por el middleware y son la fuente.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id()
        record.span_id = current_span_id()
        record.request_id = current_request_id()
        record.celery_task_id = _celery_task_id()
        if not all(hasattr(record, name) for name in ("route", "app", "user_id")):
            route, app, user_id = _scope_fields()
            for name, value in (("route", route), ("app", app), ("user_id", user_id)):
                if not hasattr(record, name):
                    setattr(record, name, value)
        return True


# ---------------------------------------------------------------------------
# Formateadores
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro.

    Claves fijas: `ts` (ISO-8601 UTC con `Z`, independiente de APP_TZ),
    `level` (`levelname` tal cual: Loki deriva `detected_level` de esa clave),
    `logger`, `msg` y los campos de contexto. Después, los `extra` del
    registro tal cual (la línea-resumen trae `method`, `status` como int y
    `duration_ms` como float). `exc_type`/`exc_info` solo con excepción, el
    traceback en UNA cadena: `json.dumps` escapa los saltos de línea.

    PRIVACIDAD: TODO lo que llegue por `extra=` sale como campo JSON de primer
    nivel, tal cual, y va a Loki (retención de semanas, lo lee cualquiera con
    acceso a Grafana). Nunca meter en `extra=` (ni en el mensaje) secretos,
    tokens, contraseñas, cookies ni PII (CURP, correo, teléfono): ids
    internos sí. Desde R6 los `logger.info` de la app se emiten, así que esto
    aplica también a los INFO que antes nadie veía.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in CONTEXT_FIELDS:
            payload[name] = getattr(record, name, "")
        for name, value in record.__dict__.items():
            if (
                name not in _STANDARD_ATTRS
                and name not in _DROPPED_EXTRAS
                and name not in payload
            ):
                payload[name] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # `default=str` no cubre CLAVES no serializables (una tupla) ni
            # referencias circulares: sin esto logging imprime "--- Logging
            # error ---" en varias líneas de texto y el registro se pierde.
            safe = {
                key: value if isinstance(value, (str, int, float, bool)) or value is None
                else str(value)
                for key, value in payload.items()
            }
            return json.dumps(safe, ensure_ascii=False)


def _build_handler(log_format: str) -> logging.Handler:
    # stdout: es lo que recoge Alloy de cada contenedor. Se ata al stream
    # vigente AL CONFIGURAR (no se resuelve al emitir): el hijo prefork de
    # Celery puede cambiar `sys.stdout` por un proxy que a su vez loguea, y
    # escribir ahí se tragaría la línea.
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    setattr(handler, _OWN_MARK, True)
    return handler


# ---------------------------------------------------------------------------
# configure_logging()
# ---------------------------------------------------------------------------

def configure_logging(log_format: str | None = None, level: str | None = None) -> None:
    """Instala el handler propio en root y en los loggers de uvicorn.

    Idempotente: cada llamada reemplaza SOLO el handler propio de la anterior
    y deja intactos los ajenos (los de pytest, p. ej.). Sin argumentos lee
    `LOG_FORMAT` (`json`|`text`) y `LOG_LEVEL` de los settings. Un valor
    inválido lanza `ValueError`: se llama al arrancar, y es mejor que el
    arranque truene a que los logs se degraden en silencio.
    """
    settings = get_settings()
    log_format = (log_format or settings.LOG_FORMAT).lower()
    if log_format not in _FORMATS:
        raise ValueError(f"LOG_FORMAT inválido: {log_format!r} (use json o text)")
    level = (level or settings.LOG_LEVEL).upper()

    root = logging.getLogger()
    # Primero el nivel: si es inválido, `setLevel` lanza ValueError antes de
    # haber tocado ningún handler.
    root.setLevel(level)

    handler = _build_handler(log_format)
    for old in [h for h in root.handlers if getattr(h, _OWN_MARK, False)]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)

    # uvicorn.access no se toca: `--no-access-log` lo apaga (la línea por
    # petición la emite el middleware). `propagate=False` en los dos: con el
    # handler en ambos y propagando, cada línea de uvicorn.error saldría dos
    # veces.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False

    # La línea-resumen reemplaza al access log de uvicorn: nivel fijo en INFO
    # para que LOG_LEVEL=WARNING (R6, bajar el volumen de la app) no la calle
    # con el resto de los INFO.
    logging.getLogger(ACCESS_LOGGER_NAME).setLevel(logging.INFO)
    for name, quiet_level in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(quiet_level)
