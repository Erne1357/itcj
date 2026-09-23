"""Contexto de la petición a través de Celery y del pub/sub `task_events` (5a).

Tres saltos, cada uno con su test:

1. Publicación (`before_task_publish`): el `snapshot()` del contexto que
   encola viaja en la cabecera `itcj_ctx` del mensaje.
2. Ejecución (`task_prerun`/`task_postrun`): el cuerpo de la tarea ve los ids
   de quien la encoló, o una raíz nueva si no vino nada (beat, CLI), y al
   terminar no queda nada ligado para la siguiente tarea del mismo proceso.
3. Pub/sub (los publicadores de `task_events` -> `_handle_task_event`): el
   aviso que retransmite el tier sockets (fin de tarea o notificación) se
   procesa bajo el contexto que trae su payload, mensaje por mensaje.

Cada escenario corre en un `contextvars.Context()` nuevo: el hilo del test no
tiene ids ligados de un test anterior, y el contexto del "worker" es distinto
del de quien publica, como en producción (otro proceso).
"""
import asyncio
import contextvars
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from itcj2.observability import celery_hooks
from itcj2.observability.context import (
    bind,
    current_request_id,
    current_span_id,
    current_trace_id,
    snapshot,
)
from itcj2.tasks.base import LoggedTask
from tests.fastapi.observability._celery_helpers import (
    consume,
    memory_app,
    run_as_worker,
    unique_queue,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")

TRACE = "a" * 31 + "1"
SPAN = "b" * 15 + "2"
REQUEST = "c" * 31 + "3"
PUBLISHER = {"trace_id": TRACE, "span_id": SPAN, "request_id": REQUEST}

HOOKS_LOGGER = "itcj2.observability.celery_hooks"

app = memory_app("itcj-obs-celery-context")
_seen: list[dict] = []


@app.task(name="tests.observability.celery_context.probe", bind=True, shared=False)
def probe(self):
    _seen.append({
        "trace_id": current_trace_id(),
        "span_id": current_span_id(),
        "request_id": current_request_id(),
        "celery_request": self.request.id,
    })
    return "ok"


@pytest.fixture(autouse=True)
def _clear_seen():
    _seen.clear()
    yield
    _seen.clear()


def _in_fresh_context(fn, *args, **kwargs):
    return contextvars.Context().run(fn, *args, **kwargs)


def _publish_bound(queue: str, ids: dict = PUBLISHER, **options):
    """Encola desde un contexto con `ids` ligados (lo que hace un endpoint)."""
    def _run():
        bind(**ids)
        probe.apply_async(queue=queue, **options)

    _in_fresh_context(_run)


def _publish_unbound(queue: str, **options):
    """Encola desde un contexto sin nada ligado (beat, CLI de Celery)."""
    _in_fresh_context(lambda: probe.apply_async(queue=queue, **options))


# ---------------------------------------------------------------------------
# 1. Publicación
# ---------------------------------------------------------------------------

def test_publish_carries_the_bound_context_in_the_itcj_ctx_header():
    queue = unique_queue()

    _publish_bound(queue)

    message = consume(app, queue)
    carried = message.headers["itcj_ctx"]
    assert carried == PUBLISHER
    # Viaja dentro del sobre JSON del transporte (Redis en producción).
    assert json.loads(json.dumps(carried)) == carried


def test_publish_without_context_adds_no_header():
    queue = unique_queue()

    _publish_unbound(queue)

    assert "itcj_ctx" not in consume(app, queue).headers


def test_publish_still_happens_when_snapshot_fails(caplog):
    # Regla de oro 2: un fallo de la instrumentación jamás impide encolar.
    queue = unique_queue()

    with patch.object(celery_hooks, "snapshot", side_effect=RuntimeError("roto")):
        with caplog.at_level(logging.ERROR):
            _publish_bound(queue)

    message = consume(app, queue)
    assert message.headers["task"] == probe.name
    assert "itcj_ctx" not in message.headers
    # Lo traga NUESTRO receptor (y lo deja dicho), no el `send` de Celery.
    assert any(r.name == HOOKS_LOGGER for r in caplog.records)
    assert not [r for r in caplog.records if "Signal handler" in r.getMessage()]


# ---------------------------------------------------------------------------
# 2. Ejecución
# ---------------------------------------------------------------------------

def test_task_body_sees_the_ids_of_whoever_enqueued_it():
    queue = unique_queue()
    _publish_bound(queue)

    _in_fresh_context(run_as_worker, app, consume(app, queue))

    [seen] = _seen
    assert seen["trace_id"] == TRACE
    assert seen["request_id"] == REQUEST
    # La tarea abre su propio span: el del mensaje es el de quien encoló.
    assert _HEX16.match(seen["span_id"]) and seen["span_id"] != SPAN


def test_task_without_header_gets_a_fresh_root_per_task():
    # El caso del beat y del CLI: nada que heredar, pero cada tarea queda
    # correlacionable consigo misma.
    queue = unique_queue()
    _publish_unbound(queue)
    _publish_unbound(queue)

    worker = contextvars.Context()
    worker.run(run_as_worker, app, consume(app, queue))
    worker.run(run_as_worker, app, consume(app, queue))

    first, second = _seen
    for seen in (first, second):
        assert _HEX32.match(seen["trace_id"])
        assert _HEX16.match(seen["span_id"])
        assert _HEX32.match(seen["request_id"])
    assert first["trace_id"] != second["trace_id"]
    assert first["request_id"] != second["request_id"]


def test_malformed_header_gets_a_fresh_root():
    # Un productor viejo o ajeno: la cabecera no es un snapshot.
    queue = unique_queue()
    _publish_unbound(queue, headers={"itcj_ctx": "basura"})

    _in_fresh_context(run_as_worker, app, consume(app, queue))

    [seen] = _seen
    assert _HEX32.match(seen["trace_id"])
    assert _HEX32.match(seen["request_id"])


BAD_IDS = [
    # Un id de megas: la línea JSON pasaría el límite de Loki y se perdería.
    pytest.param("f" * 1_000_000, id="enorme"),
    # Largo justo más un salto: parte las líneas del formato de texto de dev
    # (y `$` de `re` lo dejaría pasar sin `fullmatch`).
    pytest.param(TRACE + "\n", id="salto-de-linea"),
]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_malformed_ids_in_the_header_are_replaced_by_fresh_ones(bad):
    # La cabecera la escribe cualquiera con acceso a Redis: lo que no tenga
    # forma W3C no se liga, y la tarea acuña el suyo.
    queue = unique_queue()
    _publish_unbound(
        queue,
        headers={"itcj_ctx": {"trace_id": bad, "span_id": SPAN, "request_id": bad}},
    )

    _in_fresh_context(run_as_worker, app, consume(app, queue))

    [seen] = _seen
    assert _HEX32.fullmatch(seen["trace_id"])
    assert _HEX32.fullmatch(seen["request_id"])


def test_only_the_malformed_id_of_the_header_is_replaced():
    queue = unique_queue()
    _publish_unbound(
        queue,
        headers={"itcj_ctx": {"trace_id": TRACE, "span_id": SPAN, "request_id": "x" * 64}},
    )

    _in_fresh_context(run_as_worker, app, consume(app, queue))

    [seen] = _seen
    assert seen["trace_id"] == TRACE
    assert _HEX32.fullmatch(seen["request_id"])


@app.task(
    name="tests.observability.celery_context.retry_probe",
    bind=True, shared=False, max_retries=1,
)
def retry_probe(self):
    _seen.append({
        "trace_id": current_trace_id(),
        "span_id": current_span_id(),
        "request_id": current_request_id(),
        "retries": self.request.retries,
    })
    if self.request.retries == 0:
        raise self.retry(countdown=0)
    return "ok"


def test_retry_republishes_and_continues_the_trace():
    """`Task.retry()` re-publica desde DENTRO de la tarea, con los ids ya
    restaurados por `task_prerun`: el mensaje del reintento lleva la misma
    traza y el reintento la continúa (con su propio span, hijo del intento
    que falló)."""
    queue = unique_queue()
    _in_fresh_context(lambda: (bind(**PUBLISHER), retry_probe.apply_async(queue=queue)))

    worker = contextvars.Context()
    worker.run(run_as_worker, app, consume(app, queue))
    retried = consume(app, queue)
    worker.run(run_as_worker, app, retried)

    first, second = _seen
    assert (first["retries"], second["retries"]) == (0, 1)
    carried = retried.headers["itcj_ctx"]
    assert carried["trace_id"] == TRACE and carried["request_id"] == REQUEST
    # El padre del reintento es el intento que falló, no quien encoló.
    assert carried["span_id"] == first["span_id"] != SPAN
    assert second["trace_id"] == TRACE and second["request_id"] == REQUEST
    assert _HEX16.fullmatch(second["span_id"])
    assert second["span_id"] not in (SPAN, first["span_id"])
    # Ninguno de los dos intentos deja nada ligado en el worker.
    assert worker.run(snapshot) == {
        "trace_id": None, "span_id": None, "request_id": None,
    }


def test_nothing_stays_bound_after_the_task_in_the_same_worker():
    queue = unique_queue()
    _publish_bound(queue)
    _publish_unbound(queue)

    worker = contextvars.Context()
    worker.run(run_as_worker, app, consume(app, queue))
    assert worker.run(snapshot) == {
        "trace_id": None, "span_id": None, "request_id": None,
    }
    worker.run(run_as_worker, app, consume(app, queue))

    inherited, fresh = _seen
    assert inherited["trace_id"] == TRACE
    # La siguiente tarea del mismo proceso no hereda nada de la anterior.
    assert fresh["trace_id"] != TRACE
    assert fresh["request_id"] != REQUEST
    assert worker.run(snapshot)["trace_id"] is None


def test_headerless_task_mints_a_root_even_over_a_stale_context():
    # Si un `reset` de `task_postrun` fallara alguna vez, el worker quedaría
    # con ids ligados entre tareas: una tarea del beat (sin cabecera) debe
    # acuñar su raíz igual, no heredar en silencio la traza de otra.
    queue = unique_queue()
    _publish_unbound(queue)

    worker = contextvars.Context()
    worker.run(bind, **PUBLISHER)
    worker.run(run_as_worker, app, consume(app, queue))

    [seen] = _seen
    assert _HEX32.match(seen["trace_id"]) and seen["trace_id"] != TRACE
    assert _HEX32.match(seen["request_id"]) and seen["request_id"] != REQUEST
    # `task_postrun` deshace solo lo suyo.
    assert worker.run(snapshot) == PUBLISHER


def test_eager_apply_mints_a_root_and_gives_the_caller_its_context_back():
    # Eager no publica: no hay cabecera, así que la tarea acuña su raíz
    # aunque quien la llama tenga ids ligados (el contrato: falta la
    # cabecera -> raíz nueva), y al terminar le devuelve su contexto intacto.
    def _run():
        bind(**PUBLISHER)
        probe.apply()
        return snapshot()

    after = _in_fresh_context(_run)

    [seen] = _seen
    assert _HEX32.match(seen["trace_id"]) and seen["trace_id"] != TRACE
    assert _HEX32.match(seen["request_id"]) and seen["request_id"] != REQUEST
    assert after == PUBLISHER


def test_prerun_failure_does_not_break_the_task(caplog):
    queue = unique_queue()
    _publish_bound(queue)

    worker = contextvars.Context()
    with patch.object(celery_hooks, "new_ids", side_effect=RuntimeError("roto")):
        with caplog.at_level(logging.ERROR):
            result = worker.run(run_as_worker, app, consume(app, queue))

    assert result == "ok"
    assert len(_seen) == 1
    assert any(r.name == HOOKS_LOGGER for r in caplog.records)
    assert worker.run(snapshot)["trace_id"] is None


def test_celery_app_import_registers_the_hooks():
    """El import de efecto lateral en `itcj2/celery_app.py` es lo que conecta
    los receptores en el worker, en el beat y en los procesos HTTP que
    encolan (todos importan esa app). En un proceso limpio, sin que nadie
    importe los hooks a mano."""
    code = (
        "import sys\n"
        "import itcj2.celery_app\n"
        "print('HOOKS_LOADED=%s' % ('itcj2.observability.celery_hooks' in sys.modules))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p
    )

    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )

    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "HOOKS_LOADED=True" in proc.stdout


# ---------------------------------------------------------------------------
# De la petición al aviso de fin: LoggedTask publica en `task_events`
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, channel, raw):
        self.published.append((channel, json.loads(raw)))


@app.task(
    name="tests.observability.celery_context.logged",
    base=LoggedTask, bind=True, shared=False,
)
def logged_probe(self, task_run_id=None):
    return {"ok": True}


def test_task_event_of_a_logged_task_carries_the_request_trace():
    queue = unique_queue()
    fake = _FakeRedis()

    def _enqueue():
        bind(**PUBLISHER)
        logged_probe.apply_async(kwargs={"task_run_id": 41}, queue=queue)

    _in_fresh_context(_enqueue)
    with patch.object(LoggedTask, "_update_run", return_value=7), patch(
        "redis.from_url", return_value=fake
    ):
        _in_fresh_context(run_as_worker, app, consume(app, queue))

    [(channel, payload)] = fake.published
    assert channel == "task_events"
    assert payload["type"] == "task_completed"
    assert payload["task_run_id"] == 41
    assert payload["user_id"] == 7
    assert payload["itcj_ctx"]["trace_id"] == TRACE
    assert payload["itcj_ctx"]["request_id"] == REQUEST


# ---------------------------------------------------------------------------
# 3. Pub/sub `task_events`
# ---------------------------------------------------------------------------

def test_publish_task_event_adds_itcj_ctx_to_the_payload():
    fake = _FakeRedis()

    def _run():
        bind(**PUBLISHER)
        LoggedTask._publish_task_event(5, "SUCCESS", "some.task", 9)

    with patch("redis.from_url", return_value=fake):
        _in_fresh_context(_run)

    [(channel, payload)] = fake.published
    assert channel == "task_events"
    # Compatible hacia atrás: los campos de siempre, igual que antes.
    assert payload == {
        "type": "task_completed",
        "task_run_id": 5,
        "task_name": "some.task",
        "status": "SUCCESS",
        "user_id": 9,
        "itcj_ctx": PUBLISHER,
    }


def test_publish_task_event_still_publishes_when_snapshot_fails():
    fake = _FakeRedis()

    with patch("redis.from_url", return_value=fake), patch(
        "itcj2.tasks.base.snapshot", side_effect=RuntimeError("roto")
    ):
        _in_fresh_context(LoggedTask._publish_task_event, 5, "SUCCESS", "t", 9)

    [(_, payload)] = fake.published
    assert payload["task_run_id"] == 5
    assert "itcj_ctx" not in payload


class _FakeSession:
    """Lo único que usa `_push_user_notification` de la sesión: la prueba es
    del mensaje que publica, no del INSERT (en CI la base está vacía y una
    `Notification` real pide un usuario)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add(self, obj):
        pass

    def commit(self):
        pass

    def refresh(self, obj):
        pass


def test_helpdesk_user_notification_carries_the_task_context(monkeypatch):
    # El otro publicador de `task_events` en el worker (avisos de documento y
    # de exportación listos): también lleva el contexto de la tarea (R32).
    from itcj2.core.models.notification import Notification
    from itcj2.tasks.helpdesk_tasks import _push_user_notification

    monkeypatch.setattr("itcj2.database.SessionLocal", _FakeSession)
    monkeypatch.setattr(
        Notification, "to_dict", lambda self, **kw: {"title": self.title}
    )
    fake = _FakeRedis()

    def _run():
        bind(**PUBLISHER)
        _push_user_notification(8, "Listo", "Tu documento", None)

    with patch("redis.from_url", return_value=fake):
        _in_fresh_context(_run)

    [(channel, payload)] = fake.published
    assert channel == "task_events"
    # Compatible hacia atrás: los campos de siempre, igual que antes.
    assert payload == {
        "type": "user_notification",
        "user_id": 8,
        "notification": {"title": "Listo"},
        "itcj_ctx": PUBLISHER,
    }


def test_mass_notification_events_carry_the_task_context():
    from itcj2.tasks.notification_tasks import _push_user_notifications

    fake = _FakeRedis()
    notifications = [{"user_id": 4, "id": 1}, {"user_id": 5, "id": 2}]

    def _run():
        bind(**PUBLISHER)
        _push_user_notifications(notifications)

    with patch("redis.from_url", return_value=fake):
        _in_fresh_context(_run)

    assert [payload for _, payload in fake.published] == [
        {
            "type": "user_notification",
            "user_id": notif["user_id"],
            "notification": notif,
            "itcj_ctx": PUBLISHER,
        }
        for notif in notifications
    ]


def _task_event(**extra) -> dict:
    return {
        "type": "task_completed",
        "task_run_id": 3,
        "task_name": "some.task",
        "status": "SUCCESS",
        "user_id": 12,
        **extra,
    }


@pytest.fixture()
def pushed(monkeypatch):
    """`push_notification` falso: registra qué contexto veía al emitir."""
    import itcj2.sockets.notifications as notifications

    calls = []

    async def _fake_push(user_id, payload):
        calls.append({
            "user_id": user_id,
            "payload": payload,
            "trace_id": current_trace_id(),
            "request_id": current_request_id(),
        })

    monkeypatch.setattr(notifications, "push_notification", _fake_push)
    return calls


def _run_async(coro_fn):
    return _in_fresh_context(asyncio.run, coro_fn())


def test_handle_task_event_runs_under_the_payload_context(pushed):
    from itcj2.main import _handle_task_event

    async def _scenario():
        await _handle_task_event(_task_event(itcj_ctx=PUBLISHER))
        # Scoped al mensaje: al volver, nada queda ligado.
        return snapshot()

    after = _run_async(_scenario)

    [call] = pushed
    assert call["trace_id"] == TRACE
    assert call["request_id"] == REQUEST
    assert call["user_id"] == 12
    assert call["payload"]["task_run_id"] == 3
    assert after == {"trace_id": None, "span_id": None, "request_id": None}


@pytest.mark.parametrize(
    "extra",
    [{}, {"itcj_ctx": None}, {"itcj_ctx": "basura"}, {"itcj_ctx": {"scope": "x"}}],
    ids=["sin-campo", "null", "no-dict", "sin-ids"],
)
def test_handle_task_event_without_usable_context_still_relays(pushed, extra):
    # Despliegue mixto: un worker viejo publica sin `itcj_ctx`.
    from itcj2.main import _handle_task_event

    _run_async(lambda: _handle_task_event(_task_event(**extra)))

    [call] = pushed
    assert call["user_id"] == 12
    assert call["trace_id"] == ""


@pytest.mark.parametrize("bad", BAD_IDS)
def test_handle_task_event_drops_malformed_ids_and_still_relays(pushed, bad):
    from itcj2.main import _handle_task_event

    carried = {"trace_id": bad, "span_id": SPAN, "request_id": REQUEST + "\n"}
    _run_async(lambda: _handle_task_event(_task_event(itcj_ctx=carried)))

    [call] = pushed
    assert call["user_id"] == 12
    assert call["trace_id"] == ""
    assert call["request_id"] == ""


def test_handle_task_event_keeps_the_well_formed_ids(pushed):
    from itcj2.main import _handle_task_event

    carried = {"trace_id": TRACE, "span_id": SPAN, "request_id": "x" * 64}
    _run_async(lambda: _handle_task_event(_task_event(itcj_ctx=carried)))

    [call] = pushed
    assert call["trace_id"] == TRACE
    assert call["request_id"] == ""


def test_relayed_task_event_log_line_carries_the_payload_trace(pushed, caplog):
    """Sin una línea del tier sockets bajo el contexto del mensaje, la consulta
    de Loki por `trace_id` nunca encontraría `service="sockets"`: el camino
    feliz de `push_notification` no loguea nada."""
    from itcj2.main import _handle_task_event

    seen = []

    class _Capture(logging.Handler):
        def emit(self, record):
            seen.append((record.getMessage(), current_trace_id()))

    handler = _Capture()
    itcj2_logger = logging.getLogger("itcj2")
    itcj2_logger.addHandler(handler)
    try:
        with caplog.at_level(logging.INFO, logger="itcj2"):
            _run_async(lambda: _handle_task_event(_task_event(itcj_ctx=PUBLISHER)))
    finally:
        itcj2_logger.removeHandler(handler)

    relayed = [trace for msg, trace in seen if "task_events" in msg]
    assert relayed == [TRACE]


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def subscribe(self, channel):
        self.channel = channel

    async def listen(self):
        for message in self._messages:
            yield message
        # El subscriber real vive hasta el shutdown: así lo termina el lifespan.
        raise asyncio.CancelledError


class _FakeAsyncRedis:
    def __init__(self, messages):
        self._pubsub = _FakePubSub(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def pubsub(self):
        return self._pubsub


def test_subscriber_scopes_the_context_to_each_message(pushed):
    """UN solo task de larga vida atiende todos los mensajes: el contexto de
    un mensaje no puede filtrarse al siguiente."""
    from itcj2.main import _redis_task_subscriber

    other = {"trace_id": "d" * 32, "span_id": "e" * 16, "request_id": "f" * 32}
    messages = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": json.dumps(_task_event(itcj_ctx=PUBLISHER))},
        {"type": "message", "data": json.dumps(_task_event())},
        {"type": "message", "data": "{no es json"},
        {"type": "message", "data": json.dumps(_task_event(itcj_ctx=other))},
    ]

    async def _scenario():
        await _redis_task_subscriber()
        return snapshot()

    with patch("redis.asyncio.from_url", return_value=_FakeAsyncRedis(messages)):
        after = _run_async(_scenario)

    assert [call["trace_id"] for call in pushed] == [TRACE, "", "d" * 32]
    assert after["trace_id"] is None


def test_subscriber_error_line_carries_the_message_trace(monkeypatch):
    """La línea de un aviso que FALLA es la que más se busca en un incidente:
    sale bajo el contexto de su mensaje (con su `trace_id`), y el subscriber
    sigue con el siguiente sin arrastrarlo."""
    import itcj2.sockets.notifications as notifications
    from itcj2.main import _redis_task_subscriber

    pushed = []

    async def _flaky_push(user_id, payload):
        if payload.get("task_run_id") == 1:
            raise RuntimeError("socket caído")
        pushed.append(current_trace_id())

    monkeypatch.setattr(notifications, "push_notification", _flaky_push)

    other = {"trace_id": "d" * 32, "span_id": "e" * 16, "request_id": "f" * 32}
    messages = [
        {"type": "message", "data": json.dumps(
            _task_event(task_run_id=1, itcj_ctx=PUBLISHER)
        )},
        {"type": "message", "data": json.dumps(_task_event(itcj_ctx=other))},
    ]

    seen = []

    class _Capture(logging.Handler):
        def emit(self, record):
            seen.append((record.levelno, record.getMessage(), current_trace_id()))

    handler = _Capture(level=logging.ERROR)
    itcj2_logger = logging.getLogger("itcj2")
    itcj2_logger.addHandler(handler)
    try:
        with patch("redis.asyncio.from_url", return_value=_FakeAsyncRedis(messages)):
            _run_async(_redis_task_subscriber)
    finally:
        itcj2_logger.removeHandler(handler)

    errors = [(msg, trace) for level, msg, trace in seen if level >= logging.ERROR]
    assert errors == [
        ("Redis subscriber: error procesando mensaje: socket caído", TRACE),
    ]
    # El siguiente mensaje se retransmite, bajo SU contexto.
    assert pushed == ["d" * 32]


def test_hooks_module_imports_only_context_from_itcj2():
    """Regla de oro 1: los hooks viven en la cadena de imports de Celery, que
    no puede cargar `prometheus_client` (ver
    `test_celery_arranca_aunque_herede_prometheus_multiproc_dir`). Lo único de
    itcj2 que pueden importar es `context`."""
    import ast

    source = (REPO_ROOT / "itcj2" / "observability" / "celery_hooks.py").read_text(
        encoding="utf-8"
    )
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert {m for m in imported if m.startswith("itcj2")} == {
        "itcj2.observability.context"
    }


def test_each_hook_is_connected_once_by_strong_reference():
    # Con referencia débil, un receptor que nadie más retenga lo recoge el GC
    # y la propagación se apaga en silencio; conectado dos veces, el segundo
    # `task_prerun` pisaría los tokens del primero y ese `bind` quedaría sin
    # deshacer.
    from celery.signals import before_task_publish, task_postrun, task_prerun

    for signal in (before_task_publish, task_prerun, task_postrun):
        ours = [
            receiver for _, receiver in signal.receivers
            if getattr(receiver, "__module__", None) == HOOKS_LOGGER
        ]
        assert len(ours) == 1, signal
