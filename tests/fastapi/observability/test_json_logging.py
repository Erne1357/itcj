"""Tests de `itcj2.observability.logging_config`: una línea JSON por registro.

Se lee lo que escribe el handler propio: el buffer del fixture `json_logs`, o
stdout (`capsys`) en los tests que prueban el destino, que es el contrato con
Alloy/Loki (recogen el stdout de los contenedores). Esos tests llaman a
`configure_logging()` en su cuerpo, cuando `capsys` ya cambió `sys.stdout`. El
fixture autouse deja el logging como estaba al terminar: un handler atado a un
buffer ya cerrado haría fallar cualquier log posterior de la suite.

App de prueba igual que `test_middleware.py`: `setup_middleware()` real (JWT,
CORS y el middleware de observabilidad) y los handlers de error REALES de
`itcj2/main.py`. Sin BD ni datos sembrados.
"""
import contextvars
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from itcj2.main import _register_error_handlers
from itcj2.middleware import setup_middleware
from itcj2.observability.logging_config import configure_logging
from tests.conftest import TEST_SECRET, make_jwt

# Un logger cualquiera, como el de cualquier servicio: la app no toca sus
# ~40 módulos, sus líneas ganan el contexto por el handler de root.
logger = logging.getLogger(__name__)

PREFIX = "/api/help-desk/v2/obs-log"
ITEM_TEMPLATE = f"{PREFIX}/items/{{item_id}}"

CONTEXT_FIELDS = ("trace_id", "span_id", "request_id", "user_id", "route", "app")
BASE_FIELDS = ("ts", "level", "logger", "msg")

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")

# Loggers que `configure_logging()` toca (o que un test altera a propósito).
_TOUCHED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "itcj2.access",
    "httpx",
    "httpcore",
    "urllib3",
    "watchfiles",
    "msal",
    "socketio.server",
    "engineio.server",
)


def _is_own(handler) -> bool:
    return getattr(handler, "_itcj_observability", False)


@pytest.fixture(autouse=True)
def _restore_logging():
    """Deja el logging exactamente como estaba antes del test.

    En root NO se reasigna `root.handlers` completo: pytest pone y quita sus
    propios handlers (caplog, reporte) en cada fase, y reponer la lista de la
    fase de setup dejaría colgados handlers de pytest para siempre. Solo se
    quitan los handlers propios que dejó el test y se reponen los que había.
    """
    root = logging.getLogger()
    root_level = root.level
    own_before = [h for h in root.handlers if _is_own(h)]
    saved = {}
    for name in _TOUCHED_LOGGERS:
        lg = logging.getLogger(name)
        saved[name] = (lg.level, list(lg.handlers), lg.propagate)

    yield

    for handler in [h for h in root.handlers if _is_own(h)]:
        root.removeHandler(handler)
    for handler in own_before:
        root.addHandler(handler)
    root.setLevel(root_level)
    for name, (level, handlers, propagate) in saved.items():
        lg = logging.getLogger(name)
        lg.setLevel(level)
        lg.handlers = handlers
        lg.propagate = propagate


class ProbeBoomError(Exception):
    """Excepción propia: su nombre en `exc_type` prueba que sale el tipo REAL."""


def _build_app() -> FastAPI:
    app = FastAPI()
    setup_middleware(app)
    _register_error_handlers(app)

    router = APIRouter(prefix="/items")

    # `def` (no `async def`) a propósito: corre en el threadpool de anyio, la
    # frontera de hilo que el contexto tiene que cruzar para llegar al log.
    @router.get("/{item_id}")
    def item(item_id: int):
        logger.info("dentro del endpoint %s", item_id)
        return {"ok": True}

    @router.get("/{item_id}/boom")
    def boom(item_id: int):
        logger.info("antes de reventar")
        raise ProbeBoomError("explota a propósito")

    @router.get("/{item_id}/spoof")
    def spoof(item_id: int):
        # Un `extra` con el nombre de un id de contexto. Ningún código de la
        # app lo hace (lo vigila `test_no_app_log_extra_uses_a_context_id_key`),
        # pero la precedencia tiene que aguantar si alguien lo cuela.
        logger.info("extra que choca", extra={"request_id": 57})
        return {"ok": True}

    app.include_router(router, prefix=PREFIX)
    return app


@pytest.fixture()
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        # raise_server_exceptions=False: ServerErrorMiddleware re-lanza después
        # de mandar el 500; sin esto el TestClient la re-lanzaría en el test.
        with TestClient(_build_app(), raise_server_exceptions=False) as c:
            yield c


def _parse(out: str) -> list[dict]:
    """Cada línea no vacía de stdout TIENE que ser un JSON: un traceback con
    saltos de línea crudos rompería aquí, que es justo lo que se prueba."""
    records = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:  # pragma: no cover - mensaje del fallo
            raise AssertionError(f"línea de log que no es JSON: {line!r}") from exc
    return records


class _OwnOutput:
    """Lo que escribe el handler propio, leído y vaciado en cada llamada."""

    def __init__(self, buffer: io.StringIO):
        self._buffer = buffer

    def text(self) -> str:
        out = self._buffer.getvalue()
        self._buffer.seek(0)
        self._buffer.truncate()
        return out

    def records(self) -> list[dict]:
        return _parse(self.text())


@pytest.fixture()
def json_logs() -> _OwnOutput:
    """Logging en JSON con el handler propio escribiendo a un buffer.

    No sirve `capsys` aquí: pytest cierra el buffer de la fase de setup y abre
    otro para la de call, así que un handler configurado en un fixture quedaría
    atado al ya cerrado. Que el destino real es stdout lo prueban los tests que
    configuran dentro de su cuerpo (`capsys`).
    """
    configure_logging(log_format="json", level="INFO")
    [handler] = [h for h in logging.getLogger().handlers if _is_own(h)]
    buffer = io.StringIO()
    handler.setStream(buffer)
    return _OwnOutput(buffer)


def _by_msg(records: list[dict], prefix: str) -> dict:
    [record] = [r for r in records if r["msg"].startswith(prefix)]
    return record


def _access(records: list[dict]) -> dict:
    [record] = [r for r in records if r["logger"] == "itcj2.access"]
    return record


# ---------------------------------------------------------------------------
# Líneas dentro de una petición
# ---------------------------------------------------------------------------

def test_line_inside_def_endpoint_carries_request_context(client, json_logs):
    token = make_jwt(user_id=200)

    resp = client.get(f"{PREFIX}/items/7", headers={"Cookie": f"itcj_token={token}"})

    assert resp.status_code == 200
    line = _by_msg(json_logs.records(), "dentro del endpoint")
    assert line["msg"] == "dentro del endpoint 7"
    assert line["level"] == "INFO"
    assert line["logger"] == __name__
    assert _HEX32.match(line["trace_id"])
    assert _HEX16.match(line["span_id"])
    assert line["request_id"] == resp.headers["x-request-id"]
    # Plantilla COMPLETA, no el tramo del router hoja ni la ruta cruda.
    assert line["route"] == ITEM_TEMPLATE
    assert line["app"] == "helpdesk"
    assert line["user_id"] == "200"


def test_summary_line_is_json_with_typed_fields(client, json_logs):
    resp = client.get(f"{PREFIX}/items/7")

    records = json_logs.records()
    summary = _access(records)
    assert summary["method"] == "GET"
    # Números como números: Loki/Grafana filtran `status >= 500` y promedian
    # `duration_ms` sin tener que convertir.
    assert type(summary["status"]) is int and summary["status"] == 200
    assert type(summary["duration_ms"]) is float and summary["duration_ms"] >= 0
    assert summary["route"] == ITEM_TEMPLATE
    assert summary["app"] == "helpdesk"
    assert summary["user_id"] == ""
    assert summary["level"] == "INFO"
    assert "exc_type" not in summary
    # La misma petición: el id une la línea del endpoint con la de resumen.
    inner = _by_msg(records, "dentro del endpoint")
    assert summary["request_id"] == inner["request_id"] == resp.headers["x-request-id"]
    assert summary["trace_id"] == inner["trace_id"]


def test_extra_cannot_spoof_the_request_id(client, json_logs):
    # El request_id es la llave para unir líneas en Loki: un `extra` con el
    # mismo nombre no la pisa.
    resp = client.get(f"{PREFIX}/items/7/spoof")

    line = _by_msg(json_logs.records(), "extra que choca")
    assert line["request_id"] == resp.headers["x-request-id"]


# Ids que `ContextFilter` escribe SIEMPRE desde el contexto de la petición.
_CONTEXT_ID_KEYS = frozenset({"trace_id", "span_id", "request_id"})


def _extra_keys_that_collide(tree) -> list:
    """`(línea, clave)` de cada `extra={...}` literal con una clave de
    `_CONTEXT_ID_KEYS`."""
    import ast

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue
            for key in keyword.value.keys:
                if isinstance(key, ast.Constant) and key.value in _CONTEXT_ID_KEYS:
                    hits.append((key.lineno, key.value))
    return sorted(hits)


def test_no_app_log_extra_uses_a_context_id_key():
    """Un `extra={"request_id": <id de BD>}` lo PISA en silencio el filtro de
    contexto con el id HTTP: la línea pierde justo el dato que quería dejar
    (así estaban tres INFO de agendatec, visibles por primera vez con R6).
    Hay que nombrarlo por lo que es: `agendatec_request_id`, etc."""
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[3] / "itcj2"
    offenders = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, key in _extra_keys_that_collide(tree):
            offenders.append(f"{path.relative_to(package.parent)}:{lineno} {key!r}")

    assert offenders == [], (
        "extra= con una clave que ContextFilter sobrescribe con el id de la "
        f"petición (renómbrala, p. ej. '<app>_request_id'): {offenders}"
    )


def test_collision_scan_detects_a_colliding_extra():
    # Sin esto el escáner podría estar roto y el test de arriba pasaría en
    # vacío.
    import ast

    tree = ast.parse(
        'log.info("x", extra={"request_id": 1, "agendatec_request_id": 2})\n'
        'log.info("y", extra={"span_id": 3})\n'
    )
    assert _extra_keys_that_collide(tree) == [(1, "request_id"), (2, "span_id")]


def test_unhandled_500_line_carries_the_request_id(client, json_logs):
    resp = client.get(f"{PREFIX}/items/5/boom")

    assert resp.status_code == 500
    records = json_logs.records()
    before = _by_msg(records, "antes de reventar")
    summary = _access(records)
    # R4: el logger.exception del handler global corre en ServerErrorMiddleware,
    # POR FUERA del middleware, y aun así lleva el contexto de la petición.
    unhandled = _by_msg(records, "Unhandled exception")
    assert _HEX32.match(before["request_id"])
    assert unhandled["request_id"] == before["request_id"] == summary["request_id"]
    assert unhandled["route"] == f"{ITEM_TEMPLATE}/boom"
    assert unhandled["level"] == "ERROR"
    assert unhandled["exc_type"] == "ProbeBoomError"
    assert "Traceback" in unhandled["exc_info"]
    assert "ProbeBoomError: explota a propósito" in unhandled["exc_info"]
    assert summary["status"] == 500
    assert summary["exc_type"] == "ProbeBoomError"


# ---------------------------------------------------------------------------
# Líneas fuera de una petición
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method, levelname",
    [("warning", "WARNING"), ("error", "ERROR"), ("critical", "CRITICAL")],
)
def test_line_without_context_has_every_field_empty(json_logs, method, levelname):
    # Contexto vacío garantizado: ningún test anterior puede dejar ids
    # ligados en este hilo.
    contextvars.Context().run(getattr(logger, method), "sin contexto")

    [line] = json_logs.records()
    for field in BASE_FIELDS + CONTEXT_FIELDS:
        assert field in line, f"falta {field!r}: {line}"
    for field in CONTEXT_FIELDS:
        assert line[field] == "", f"{field!r} debería ir vacío: {line}"
    assert line["level"] == levelname
    assert line["msg"] == "sin contexto"
    assert "exc_type" not in line and "exc_info" not in line


def test_ts_is_iso8601_utc_with_z(json_logs):
    logger.warning("reloj")

    [line] = json_logs.records()
    assert line["ts"].endswith("Z")
    ts = datetime.fromisoformat(line["ts"])
    assert ts.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - ts) < timedelta(minutes=1)


def test_exception_is_a_single_line_with_exc_type_and_exc_info(json_logs):
    try:
        raise ValueError("uno\ndos")
    except ValueError:
        logger.exception("falló la cosa")

    out = json_logs.text()
    # UNA línea física: el traceback va escapado dentro del JSON.
    assert out.count("\n") == 1 and out.endswith("\n")
    [line] = _parse(out)
    assert line["msg"] == "falló la cosa"
    assert line["level"] == "ERROR"
    assert line["exc_type"] == "ValueError"
    assert "Traceback" in line["exc_info"]
    assert "ValueError: uno\ndos" in line["exc_info"]


def test_unserializable_extra_still_yields_one_json_line(json_logs):
    # `default=str` no cubre CLAVES: una tupla como clave haría fallar
    # json.dumps y logging imprimiría "--- Logging error ---" en varias líneas.
    logger.warning("extra raro", extra={"data": {(1, 2): "x"}})

    [line] = json_logs.records()
    assert line["msg"] == "extra raro"
    assert "(1, 2)" in line["data"]


# ---------------------------------------------------------------------------
# Formato de texto (dev, R5)
# ---------------------------------------------------------------------------

def test_text_format_is_readable_and_includes_request_id(capsys, client):
    configure_logging(log_format="text", level="INFO")
    capsys.readouterr()

    resp = client.get(f"{PREFIX}/items/7")

    out = capsys.readouterr().out
    [line] = [ln for ln in out.splitlines() if "dentro del endpoint 7" in ln]
    assert not line.lstrip().startswith("{")
    assert resp.headers["x-request-id"] in line
    assert "INFO" in line


# ---------------------------------------------------------------------------
# configure_logging(): idempotencia, handlers ajenos, niveles
# ---------------------------------------------------------------------------

def test_configure_logging_is_idempotent_and_keeps_foreign_handlers(capsys, caplog):
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        for _ in range(5):
            configure_logging(log_format="json", level="INFO")
        capsys.readouterr()

        logger.warning("una sola vez")

        assert len([h for h in root.handlers if _is_own(h)]) == 1
        assert foreign in root.handlers
        assert caplog.handler in root.handlers
        [line] = _parse(capsys.readouterr().out)
        assert line["msg"] == "una sola vez"
        # El handler de caplog siguió recibiendo registros.
        assert "una sola vez" in caplog.text
    finally:
        root.removeHandler(foreign)


def test_uvicorn_loggers_use_the_own_handler_once(capsys):
    # Simula el dictConfig de uvicorn, que cuelga su handler de texto en
    # "uvicorn" ANTES de importar la app.
    logging.getLogger("uvicorn").addHandler(logging.StreamHandler())

    configure_logging(log_format="json", level="INFO")
    capsys.readouterr()

    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        assert len(lg.handlers) == 1 and _is_own(lg.handlers[0]), name
        assert lg.propagate is False, name

    logging.getLogger("uvicorn.error").info("Started server process [%d]", 7)

    [line] = _parse(capsys.readouterr().out)
    assert line["logger"] == "uvicorn.error"
    assert line["msg"] == "Started server process [7]"


def test_uvicorn_color_message_extra_is_dropped(json_logs):
    # uvicorn duplica cada mensaje con códigos ANSI en `color_message`.
    logging.getLogger("uvicorn.error").info(
        "Started server process [%d]",
        7,
        extra={"color_message": "Started server process [\x1b[36m%d\x1b[0m]"},
    )

    [line] = json_logs.records()
    assert "color_message" not in line


@pytest.mark.parametrize(
    "name", ["httpx", "httpcore", "urllib3", "watchfiles", "msal"]
)
def test_noisy_libraries_are_raised_to_warning(json_logs, name):
    logging.getLogger(name).info("ruido por petición")

    assert logging.getLogger(name).level == logging.WARNING
    assert json_logs.records() == []


def test_socketio_does_not_attach_its_own_text_handler(capsys):
    """python-socketio/engineio con `logger=False` cuelgan un StreamHandler de
    texto en stderr si su logger está en NOTSET al construir el servidor: cada
    ERROR saldría dos veces, una sin formato JSON."""
    import socketio

    # Como en un proceso recién arrancado (el fixture autouse lo repone).
    for name in ("socketio.server", "engineio.server"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.NOTSET)
        lg.handlers = []

    configure_logging(log_format="json", level="INFO")
    socketio.AsyncServer(async_mode="asgi", logger=False, engineio_logger=False)
    capsys.readouterr()

    for name in ("socketio.server", "engineio.server"):
        assert logging.getLogger(name).handlers == [], name
    logging.getLogger("socketio.server").error("fallo del socket")

    captured = capsys.readouterr()
    assert captured.err == ""
    [line] = _parse(captured.out)
    assert line["msg"] == "fallo del socket"


def test_summary_line_survives_log_level_warning(capsys, client):
    # R6: LOG_LEVEL=WARNING calla los logger.info de la app, pero la línea por
    # petición reemplaza al access log de uvicorn: no puede desaparecer.
    configure_logging(log_format="json", level="WARNING")
    capsys.readouterr()

    client.get(f"{PREFIX}/items/7")

    records = _parse(capsys.readouterr().out)
    assert _access(records)["status"] == 200
    assert not [r for r in records if r["msg"].startswith("dentro del endpoint")]


@pytest.mark.parametrize(
    "kwargs",
    [{"log_format": "yaml", "level": "INFO"}, {"log_format": "json", "level": "RUIDOSO"}],
)
def test_invalid_settings_fail_loudly(kwargs):
    # Se llama como primera sentencia de create_app(): un valor inválido tumba
    # el arranque (y el gate de deploy), no degrada los logs en silencio.
    with pytest.raises(ValueError):
        configure_logging(**kwargs)


def test_configure_logging_reads_settings_by_default(capsys):
    fake = SimpleNamespace(LOG_FORMAT="text", LOG_LEVEL="WARNING")
    with patch("itcj2.observability.logging_config.get_settings", return_value=fake):
        configure_logging()
    capsys.readouterr()

    logger.info("callado")
    logger.warning("visible")

    out = capsys.readouterr().out
    assert "callado" not in out
    [line] = [ln for ln in out.splitlines() if "visible" in ln]
    assert not line.lstrip().startswith("{")


def test_settings_defaults_are_json_and_info():
    from itcj2.config import Settings

    # El default del campo, no una instancia: el contenedor de dev pone
    # LOG_FORMAT=text por entorno (R5).
    assert Settings.model_fields["LOG_FORMAT"].default == "json"
    assert Settings.model_fields["LOG_LEVEL"].default == "INFO"


def test_filter_does_not_recurse_when_the_route_map_logs_while_building(capsys):
    """El filtro resuelve la plantilla en diferido; el PRIMER log de una app
    arma su mapa de rutas, y armarlo puede emitir un warning (el mismo router
    incluido bajo dos prefijos), que vuelve a pasar por el filtro. Sin un
    candado, cada vuelta reconstruye el mapa y emite otro warning."""
    app = FastAPI()
    setup_middleware(app)
    router = APIRouter()

    @router.get("/dup")
    def dup():
        logger.info("dentro de la ruta duplicada")
        return {"ok": True}

    app.include_router(router, prefix="/api/help-desk/v2/uno")
    app.include_router(router, prefix="/api/help-desk/v2/dos")

    configure_logging(log_format="json", level="INFO")
    capsys.readouterr()

    with TestClient(app) as c:
        resp = c.get("/api/help-desk/v2/uno/dup")

    assert resp.status_code == 200
    records = _parse(capsys.readouterr().out)
    warnings = [r for r in records if r["msg"].startswith("build_route_map")]
    assert len(warnings) == 1, [r["msg"] for r in records]
    _by_msg(records, "dentro de la ruta duplicada")


# ---------------------------------------------------------------------------
# Cableado: create_app() y Celery
# ---------------------------------------------------------------------------

def test_create_app_configures_logging_to_stdout(capsys):
    from itcj2.main import create_app

    create_app()
    capsys.readouterr()

    logger.warning("desde create_app")

    # Antes de este cambio root no tenía handlers: el WARNING salía por
    # logging.lastResort, a stderr y sin contexto.
    assert "desde create_app" in capsys.readouterr().out


def test_celery_setup_logging_signal_configures_logging(capsys):
    from celery import signals

    import itcj2.celery_app  # noqa: F401  (conecta el receptor al importarse)

    # Lo mismo que hace Celery al arrancar worker y beat. Con receptores,
    # `setup_logging_subsystem` se salta `worker_hijack_root_logger`.
    responses = signals.setup_logging.send(
        sender=None, loglevel=logging.INFO, logfile=None, format="", colorize=False
    )
    capsys.readouterr()

    assert responses, "ningún receptor: Celery secuestraría el root logger"
    logger.warning("desde celery")
    assert "desde celery" in capsys.readouterr().out
