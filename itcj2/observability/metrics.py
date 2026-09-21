"""Métricas de Prometheus de ITCJ y su exposición en `GET /metrics`.

R18: TODOS los objetos de métrica `itcj_*` se declaran aquí, a nivel de
módulo y nunca dentro de `create_app()` (una segunda app en el mismo proceso,
p. ej. en tests, intentaría registrarlos otra vez). Los módulos que los
alimentan (middleware, saturación, lag del loop) solo los actualizan.

Modo multiproceso (plan §9.2): producción corre `uvicorn --workers 4`, cuatro
procesos detrás de un puerto. Sin `PROMETHEUS_MULTIPROC_DIR` cada worker
tendría su propio registro y el scrape caería en uno al azar: un tablero con
la cuarta parte del tráfico que parece plausible — números EQUIVOCADOS, no
ausentes. Con la variable puesta (la exporta el entrypoint ANTES de arrancar
uvicorn: `prometheus_client` elige la clase de valores al importarse), cada
proceso escribe sus valores en ficheros mmap de ese directorio y
`MultiProcessCollector` los suma todos al atender el scrape, caiga en el
worker que caiga.

Sin exemplars (plan §9.3): en modo multiproceso `set_exemplar` es un no-op de
`prometheus_client` (comprobado en 0.26.0: `MmapedValue.set_exemplar` solo
hace `return`), así que no hay forma de colgar un `trace_id` de un bucket. El
puente entre "este panel tiene un pico" y "esta petición es la culpable" va
por Loki: la línea-resumen de cada petición (`itcj2.access`) lleva `route`,
`duration_ms`, `status` y `trace_id`, y se filtra con
`{project="itcj"} | json | route="X" | duration_ms > 1000`.
"""
import logging
import os
import re

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.multiprocess import MultiProcessCollector, mark_process_dead

logger = logging.getLogger("itcj2.observability")

# ---------------------------------------------------------------------------
# RED por petición HTTP (Fase 2)
# ---------------------------------------------------------------------------
# Nunca `multiprocess_mode='all'` ni `'liveall'`: añaden una etiqueta `pid`,
# y con workers que uvicorn respawnea cada respawn deja un juego de series
# muertas para siempre.

# Tope de 30 s: el `proxy_read_timeout 60s` de nginx es la frontera exterior;
# más allá el cliente ya vio un 504. 11 buckets (R13): el recorte, si hace
# falta, se decide con la medición de 24 h (plan §6, palanca 3).
DURATION_BUCKETS = (0.005, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

HTTP_REQUESTS = Counter(
    "itcj_http_requests_total",
    "Peticiones HTTP atendidas, por ruta plantillada y status.",
    ("app", "method", "route", "status"),
)

# SIN `status` (plan §6): lo multiplicaría por ~3 y es la métrica más cara
# (11 buckets + Inf + sum + count por par). El status ya va en el contador.
HTTP_REQUEST_DURATION = Histogram(
    "itcj_http_request_duration_seconds",
    "Duración de las peticiones HTTP, por ruta plantillada.",
    ("app", "method", "route"),
    buckets=DURATION_BUCKETS,
)

# `livesum` suma los procesos VIVOS, pero solo deja de sumar uno muerto si
# alguien llama `mark_process_dead(pid)`: de eso se encarga
# `reap_dead_workers()` en cada scrape.
HTTP_IN_FLIGHT = Gauge(
    "itcj_http_requests_in_flight",
    "Peticiones HTTP en curso.",
    ("app",),
    multiprocess_mode="livesum",
)

HTTP_EXCEPTIONS = Counter(
    "itcj_http_exceptions_total",
    "Excepciones no controladas que salieron del endpoint.",
    ("app", "route", "exc_type"),
)


# ---------------------------------------------------------------------------
# Saturación (Fase 3) — los actualiza `saturation.update_gauges()`
# ---------------------------------------------------------------------------
# Gauges REALES con `.set()` desde cada worker, no un colector personalizado:
# un colector corre solo en el worker que atiende el scrape, su salida nunca
# pasa por los ficheros mmap, y se publicaría el pool de 1 de los 4 workers
# elegido al azar — números equivocados, no ausentes (plan Fase 3). Con
# `livesum` numerador y denominador de un ratio ya vienen sumados sobre los
# workers vivos.


def _saturation_gauge(name: str, documentation: str) -> Gauge:
    return Gauge(name, documentation, multiprocess_mode="livesum")


# Limiter de anyio: los hilos donde corren los endpoints `def` (40 tokens).
ANYIO_THREADPOOL_TOTAL = _saturation_gauge(
    "itcj_anyio_threadpool_total", "Tokens del limiter de hilos de anyio."
)
ANYIO_THREADPOOL_BORROWED = _saturation_gauge(
    "itcj_anyio_threadpool_borrowed", "Tokens del limiter de anyio en uso."
)
ANYIO_THREADPOOL_WAITING = _saturation_gauge(
    "itcj_anyio_threadpool_waiting",
    "Tareas esperando un hilo de anyio (> 0: threadpool agotado).",
)

# Executor por defecto de asyncio (`asyncio.to_thread`: handlers de sockets).
ASYNCIO_THREADPOOL_TOTAL = _saturation_gauge(
    "itcj_asyncio_threadpool_total", "max_workers del executor por defecto de asyncio."
)
ASYNCIO_THREADPOOL_THREADS = _saturation_gauge(
    "itcj_asyncio_threadpool_threads",
    "Hilos creados por el executor por defecto de asyncio (nunca baja).",
)
ASYNCIO_THREADPOOL_WAITING = _saturation_gauge(
    "itcj_asyncio_threadpool_waiting",
    "Trabajos encolados en el executor por defecto de asyncio.",
)

# Pool de SQLAlchemy. La saturación es checkedout / (size + max_overflow),
# NUNCA `overflow` a secas (ver `saturation.py`).
DB_POOL_SIZE = _saturation_gauge("itcj_db_pool_size", "pool_size del engine.")
DB_POOL_CHECKEDIN = _saturation_gauge(
    "itcj_db_pool_checkedin", "Conexiones ociosas en el pool."
)
DB_POOL_CHECKEDOUT = _saturation_gauge(
    "itcj_db_pool_checkedout", "Conexiones prestadas del pool."
)
DB_POOL_OVERFLOW = _saturation_gauge(
    "itcj_db_pool_overflow",
    "QueuePool.overflow() crudo: arranca en -pool_size (no es un error).",
)
DB_POOL_MAX_OVERFLOW = _saturation_gauge(
    "itcj_db_pool_max_overflow", "max_overflow configurado (DB_MAX_OVERFLOW)."
)

# ---------------------------------------------------------------------------
# Lag del event loop (Fase 3) — lo observa `loop_lag.run_probe()`
# ---------------------------------------------------------------------------
# Hace falsable el arreglo de la Fase 6: cuánto tarda el loop en despertar
# una corrutina que pidió dormir, por encima de lo pedido.
LOOP_LAG_BUCKETS = (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5)

EVENT_LOOP_LAG = Histogram(
    "itcj_event_loop_lag_seconds",
    "Retraso del event loop al despertar una corrutina dormida.",
    buckets=LOOP_LAG_BUCKETS,
)


# ---------------------------------------------------------------------------
# Reaper de gauges `live*` de workers muertos (plan §9.16)
# ---------------------------------------------------------------------------
# `livesum` NO detecta procesos muertos: el fichero `gauge_livesum_<pid>.db`
# de un worker que murió se sigue sumando para siempre, y el in-flight (y los
# gauges de saturación de la Fase 3) suben de forma monótona con cada
# respawn — parece una fuga de peticiones y no lo es. El sitio documentado
# para `mark_process_dead` es el hook `child_exit` de gunicorn, pero aquí se
# corre `uvicorn --workers` sin gunicorn, y el supervisor de uvicorn
# (`uvicorn.supervisors.multiprocess.Multiprocess`) no expone ningún callback
# de salida de worker. Por eso se barre en cada scrape: a un scrape cada 30 s
# el coste es un `listdir` y unos cuantos `os.kill(pid, 0)`.
#
# Los PIDs solo significan algo dentro del contenedor: el directorio tiene que
# ser propio de cada contenedor (un tmpfs), nunca compartido entre ellos.
_LIVE_GAUGE_FILE = re.compile(r"^gauge_live[a-z]+_(\d+)\.db$")


def reap_dead_workers(path: str | None = None) -> list[int]:
    """Deja de sumar los gauges `live*` de los PIDs que ya no existen.

    Solo borra ficheros `gauge_live*_<pid>.db` (vía `mark_process_dead`):
    los de counter e histogram de un worker muerto se quedan, porque sus
    peticiones cuentan. Nunca lanza: un fallo aquí no puede tirar el scrape.
    Regresa los PIDs barridos.
    """
    reaped = []
    try:
        path = path or os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if not path or not os.path.isdir(path):
            return reaped
        pids = {
            int(match.group(1))
            for match in map(_LIVE_GAUGE_FILE.match, os.listdir(path))
            if match
        }
        for pid in sorted(pids):
            try:
                # Comprobado justo antes de borrar: acota la carrera con un
                # worker que siga escribiendo.
                os.kill(pid, 0)
            except ProcessLookupError:
                mark_process_dead(pid, path)
                reaped.append(pid)
            except PermissionError:
                # Existe pero es de otro usuario: vivo.
                continue
    except Exception:
        logger.exception("reap_dead_workers: no se pudo barrer %r", path)
    return reaped


# ---------------------------------------------------------------------------
# Exposición
# ---------------------------------------------------------------------------
# Colectores evaluados a la hora del scrape que se sirven además de las
# métricas del registro (Task 8: presencia y conexiones de sockets, que
# viven en Redis y solo registra el rol socket/all). No se registran en
# REGISTRY porque en modo multiproceso el scrape se arma sobre un registro
# nuevo que solo lee los ficheros mmap.
_scrape_collectors: list = []


def register_scrape_collector(collector) -> None:
    """Añade un colector (objeto con `collect()`) a la salida de `/metrics`."""
    _scrape_collectors.append(collector)


class _ScrapeView:
    """Lo que `generate_latest` recorre: la base más los colectores extra."""

    def __init__(self, base, extras):
        self._base = base
        self._extras = extras

    def collect(self):
        yield from self._base.collect()
        for collector in self._extras:
            yield from collector.collect()


def render_latest() -> tuple[bytes, str]:
    """Cuerpo y `Content-Type` de `GET /metrics`.

    Con `PROMETHEUS_MULTIPROC_DIR`: primero el reaper, luego un
    `CollectorRegistry` nuevo con `MultiProcessCollector` (el patrón
    documentado de `prometheus_client`: el registro global de ESTE worker solo
    tiene sus propios valores). Sin la variable (tests, dev): el registro
    plano del proceso.
    """
    path = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if path:
        reap_dead_workers(path)
        base = CollectorRegistry()
        MultiProcessCollector(base, path=path)
    else:
        base = REGISTRY
    return generate_latest(_ScrapeView(base, list(_scrape_collectors))), CONTENT_TYPE_LATEST
