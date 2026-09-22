"""Cronómetro del trabajo pesado y de las llamadas salientes (plan Fase 4).

Un solo sitio para medir lo que puede ocupar un hilo del threadpool durante
segundos (LibreOffice, los Excel/CSV, MS Graph, la API de fútbol) sin repetir
un `try/finally` en cada servicio. Cuando entre OpenTelemetry (Fase 7), el
span va aquí mismo.

    with measured("orden_trabajo", "libreoffice"):
        result = subprocess.run([...], timeout=60)

    with measured_outbound("msgraph") as call:
        response = requests.post(..., timeout=30)
        call.mark_status(response.status_code)

`measured(...)` también sirve como decorador (cronómetro nuevo por llamada).

Regla de oro 1: nada de `metrics` ni `prometheus_client` al importar este
módulo. Lo importan servicios que también corren dentro de Celery, y con
`PROMETHEUS_MULTIPROC_DIR` heredada del `.env` hacia un directorio que nadie
crea, `metrics` revienta al importarse (los gauges sin etiquetas abren su
mmap al declararse): la tarea moriría al cargar. El import es perezoso (la
primera medición) y GUARDADO: si falla se avisa una vez y el trabajo sigue
sin medirse. Lo vigila
`test_celery_arranca_aunque_herede_prometheus_multiproc_dir`.

Regla de oro 2: la medición nunca cambia el negocio. Sale la MISMA excepción
(identidad), el MISMO valor de retorno, y un fallo al registrar se loguea y se
traga.

Alcance, opción (i) del plan: solo el camino HTTP se raspa. Los mismos
servicios corren en `celery-worker` (`convert_document` genera los mismos
PDF): ahí la observación cae en el registro plano del proceso, que nadie
raspa, y se pierde en silencio, a propósito. El volumen encolado se sigue por
`core_task_runs`; el panel lo dice para que nadie lea su p95 como el de todo
el sistema.

Sin `returncode` como etiqueta: es un entero abierto (cada código de salida,
y los negativos de cada señal, sería una serie nueva por cada `kind`), y sin
el stderr no explica nada. Va en la línea de log del servicio cuando es != 0.

`closed_label_ok()`, `load_metrics()` y `report_metrics_failure()` son las
piezas que reutiliza cualquier otro medidor perezoso (el `spawn()` de la Fase
5b): misma política para una etiqueta fuera de su conjunto cerrado.
"""
import logging
import os
import sys
import threading
from contextlib import contextmanager
from importlib import import_module
from time import monotonic, perf_counter
from types import MappingProxyType

from itcj2.config import get_settings

logger = logging.getLogger("itcj2.observability")

# ---------------------------------------------------------------------------
# Conjuntos cerrados de etiquetas (contrato de la ronda 2)
# ---------------------------------------------------------------------------
# Viven aquí y no en `metrics.py`: la validación no puede depender de un
# import que en Celery puede fallar. Un valor nuevo se añade AQUÍ, y el
# presupuesto de series (`test_cardinalidad.py`) lo cuenta solo.
#
# R44: cada `kind` tiene exactamente UN motor, el que usa de verdad el sitio
# que genera ese documento. Con dos conjuntos independientes el código
# permitía 10 x 4 pares y solo 10 pueden existir: el presupuesto de series
# contaba ~1.260 imposibles y el siguiente merge de una app lo ponía en rojo.
# Un par que no está aquí sigue la misma política que un valor fuera de su
# conjunto (ValueError en desarrollo; en producción no se registra y se avisa
# una vez).
DOCUMENT_KIND_ENGINE = MappingProxyType({
    "solicitud": "libreoffice",
    "orden_trabajo": "libreoffice",
    "inventory_export": "openpyxl",
    "inventory_report_equipment": "csv",
    "inventory_report_movements": "csv",
    "inventory_report_warranty": "csv",
    "inventory_report_maintenance": "csv",
    "inventory_report_lifecycle": "csv",
    "retirement_oficio": "openpyxl",  # R36: el oficio de bajas no pasa a PDF
    "agendatec_report": "xlsxwriter",
})
DOCUMENT_KINDS = frozenset(DOCUMENT_KIND_ENGINE)
DOCUMENT_ENGINES = frozenset(DOCUMENT_KIND_ENGINE.values())
_DOCUMENT_PAIRS = frozenset(DOCUMENT_KIND_ENGINE.items())
OUTBOUND_TARGETS = frozenset({"msgraph", "football_api"})
OUTCOMES = frozenset({"ok", "error", "timeout"})

_RENDER_METRIC = "itcj_document_render_seconds"
_OUTBOUND_METRIC = "itcj_outbound_request_seconds"

# ---------------------------------------------------------------------------
# Política para un valor fuera del conjunto cerrado
# ---------------------------------------------------------------------------
# Un valor fuera del conjunto es un error de programación en el llamador (sus
# etiquetas son literales). En desarrollo se quiere RUIDOSO: ValueError antes
# de que corra el bloque, para que el test de ese sitio caiga. En producción
# lanzarlo tumbaría un export por una etiqueta mal escrita (regla de oro 2):
# ahí el bloque corre igual, NO se registra nada (una serie inventada rompería
# el presupuesto de series y los paneles) y se avisa una vez.

# Una vez por (métrica, etiqueta) y no por valor: si algún día el valor sale
# de la entrada (`f"inventory_report_{tipo}"`), un set por valor crecería sin
# tope y avisaría en cada petición. Tamaño acotado por el código.
_warned_labels: set = set()
_warned_lock = threading.Lock()


def strict_labels() -> bool:
    """¿Un valor fuera del conjunto cerrado debe lanzar?

    Sí bajo pytest (`PYTEST_CURRENT_TEST` lo pone pytest en cada test) y con
    `FLASK_ENV=development` (el contenedor de dev). Hace falta la señal de
    pytest porque CI no define FLASK_ENV y gana el default de config.py,
    "production": sin ella la suite de CI correría en modo tolerante y una
    etiqueta mal escrita pasaría en verde. Se evalúa en cada llamada, no al
    importar: al recolectar los tests la variable todavía no existe.
    """
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    try:
        return get_settings().FLASK_ENV == "development"
    except Exception:
        return False


def closed_label_ok(metric: str, label: str, value, allowed: frozenset) -> bool:
    """`True` si `value` está en `allowed`.

    Si no: `ValueError` en desarrollo (`strict_labels()`); en producción
    `False` (el llamador no registra nada) y un warning por (métrica,
    etiqueta) en la vida del proceso.
    """
    try:
        if value in allowed:
            return True
    except TypeError:
        pass  # no hasheable: tampoco está en el conjunto
    if strict_labels():
        raise ValueError(
            f"{metric}: {label}={value!r} está fuera del conjunto cerrado "
            f"{sorted(allowed)}"
        )
    with _warned_lock:
        if (metric, label) in _warned_labels:
            return False
        _warned_labels.add((metric, label))
    logger.warning(
        "%s: %s=%r está fuera del conjunto cerrado %s; no se registra "
        "(aviso único para esta etiqueta en este proceso)",
        metric, label, value, sorted(allowed),
    )
    return False


# ---------------------------------------------------------------------------
# Import perezoso y guardado de `metrics` (regla de oro 1)
# ---------------------------------------------------------------------------
# Si el import falla NO se reintenta en la vida del proceso: las métricas que
# alcanzaron a declararse antes del fallo ya quedaron en el REGISTRY, así que
# un segundo intento fallaría por "Duplicated timeseries" en cada medición
# (y un import que falla no lo cachea Python: repetiría el recorrido de
# `sys.path` cada vez, la trampa medida en `context.py`). El candado evita que
# dos hilos del threadpool lo intenten a la vez y avisen dos veces.
_metrics = None
_metrics_unavailable = False
_metrics_lock = threading.Lock()


def load_metrics():
    """El módulo `itcj2.observability.metrics`, o `None` si no se pudo importar."""
    global _metrics, _metrics_unavailable
    if _metrics is not None or _metrics_unavailable:
        return _metrics
    with _metrics_lock:
        if _metrics is None and not _metrics_unavailable:
            try:
                # `import_module` y no `from … import metrics`: consulta
                # `sys.modules`, que es por donde un test simula el fallo.
                _metrics = import_module("itcj2.observability.metrics")
            except Exception:
                _metrics_unavailable = True
                logger.exception(
                    "métricas de trabajo: no se pudo importar "
                    "itcj2.observability.metrics; este proceso sigue SIN "
                    "medir (no se reintenta)"
                )
    return _metrics


# Mismo criterio que el middleware (R27): si el directorio de mmap se rompe
# falla CADA medición, y un traceback por render inundaría Loki; uno por
# minuto basta para enterarse. Sin candado a propósito: corre en hilos del
# threadpool y la carrera, en el peor caso, da un aviso de más.
_FAILURE_LOG_INTERVAL = 60.0
_last_failure_log = float("-inf")


def report_metrics_failure(where: str) -> None:
    """Avisa (con límite de frecuencia) de un fallo al registrar una métrica.

    Llamar SOLO desde un `except`: `logger.exception` toma la excepción en
    curso.
    """
    global _last_failure_log
    now = monotonic()
    if now - _last_failure_log < _FAILURE_LOG_INTERVAL:
        return
    _last_failure_log = now
    logger.exception(
        "métricas de trabajo: fallo al registrar (%s); el trabajo sigue sin "
        "medirse (siguiente aviso en %.0f s como mínimo)",
        where, _FAILURE_LOG_INTERVAL,
    )


# ---------------------------------------------------------------------------
# Clasificación del resultado
# ---------------------------------------------------------------------------
# Tipos de timeout de las librerías cliente. Se buscan en `sys.modules` y
# NUNCA se importan: una excepción de `requests` solo puede existir si
# `requests` ya está cargado, así que si el módulo no está, la excepción no es
# suya. Importarlos aquí metería `requests` y `httpx` en todo proceso que
# genere un PDF.
_CLIENT_TIMEOUTS = (
    ("subprocess", "TimeoutExpired"),  # el `timeout=60` de LibreOffice
    # `ConnectTimeout` es también `ConnectionError`: cuenta como timeout, es
    # el timeout del cliente (contrato).
    ("requests", "Timeout"),
    ("httpx", "TimeoutException"),  # Connect/Read/Write/PoolTimeout
)


def _is_timeout(exc: BaseException) -> bool:
    # Corre dentro del `except` del cronómetro: si lanzara, taparía la
    # excepción del negocio.
    try:
        if isinstance(exc, TimeoutError):  # socket, asyncio, concurrent.futures
            return True
        for module_name, attr in _CLIENT_TIMEOUTS:
            cls = getattr(sys.modules.get(module_name), attr, None)
            if isinstance(cls, type) and isinstance(exc, cls):
                return True
    except Exception:
        pass
    return False


class Measurement:
    """Lo que entrega el `with`: marca como `error` un fallo que no llegó
    como excepción. Una excepción del bloque gana sobre lo marcado."""

    __slots__ = ("failed",)

    def __init__(self) -> None:
        self.failed = False

    def mark_error(self) -> None:
        self.failed = True

    def mark_status(self, status_code) -> None:
        """Status HTTP de la respuesta: `>= 400` es `error` (contrato: `ok` es
        una respuesta < 400). Nunca lanza: un status ilegible no puede tumbar
        la llamada que se está midiendo; se ignora."""
        try:
            if int(status_code) >= 400:
                self.failed = True
        except Exception:
            pass


def _observe(attr: str, labels: dict | None, outcome: str, seconds: float) -> None:
    """Registra la observación. Nunca lanza (corre en el `finally`)."""
    if labels is None:
        return  # etiqueta fuera del conjunto en producción: ya se avisó
    try:
        metrics = load_metrics()
        if metrics is not None:
            getattr(metrics, attr).labels(outcome=outcome, **labels).observe(seconds)
    except Exception:
        try:
            report_metrics_failure(attr)
        except Exception:
            pass


def _timed(attr: str, labels: dict | None):
    """El cronómetro común (generador, lo delegan los dos context managers)."""
    measurement = Measurement()
    outcome = "ok"
    start = perf_counter()
    try:
        yield measurement
    except BaseException as exc:
        # BaseException también (KeyboardInterrupt, GeneratorExit si el bloque
        # vive en un generador que se cierra a medias): el trabajo no terminó.
        # El `raise` desnudo re-lanza el MISMO objeto y `contextmanager` lo
        # deja salir tal cual (identidad).
        outcome = "timeout" if _is_timeout(exc) else "error"
        raise
    finally:
        seconds = perf_counter() - start
        if outcome == "ok" and measurement.failed:
            outcome = "error"
        _observe(attr, labels, outcome, seconds)


@contextmanager
def measured(kind: str, engine: str):
    """Cronometra la generación de un documento en
    `itcj_document_render_seconds{kind,engine,outcome}`."""
    # Se valida al ENTRAR (antes del bloque): en desarrollo el ValueError sale
    # del `with` sin que el trabajo llegue a correr.
    kind_ok = closed_label_ok(_RENDER_METRIC, "kind", kind, DOCUMENT_KINDS)
    engine_ok = closed_label_ok(_RENDER_METRIC, "engine", engine, DOCUMENT_ENGINES)
    # El par solo se mira con los dos valores válidos: con uno inválido ya se
    # avisó (o lanzó) por él, y un segundo aviso por el par sería ruido.
    pair_ok = kind_ok and engine_ok and closed_label_ok(
        _RENDER_METRIC, "(kind, engine)", (kind, engine), _DOCUMENT_PAIRS
    )
    labels = {"kind": kind, "engine": engine} if pair_ok else None
    yield from _timed("DOCUMENT_RENDER_DURATION", labels)


@contextmanager
def measured_outbound(target: str):
    """Cronometra una llamada HTTP saliente en
    `itcj_outbound_request_seconds{target,outcome}`.

    `ok` si el bloque termina y ningún `mark_status()` vio un status >= 400;
    `error` con status >= 400 o una excepción que no es timeout; `timeout`
    con el timeout del cliente.
    """
    target_ok = closed_label_ok(_OUTBOUND_METRIC, "target", target, OUTBOUND_TARGETS)
    labels = {"target": target} if target_ok else None
    yield from _timed("OUTBOUND_REQUEST_DURATION", labels)
