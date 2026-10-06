"""El push de Socket.IO de una notificación sale desde un hilo y tras el commit.

Plan de rendimiento de TitulaTec, R5 (spec §3.6). `NotificationService.create`
siempre guarda la notificación en BD; lo que va aparte es el push en tiempo
real. Antes, `broadcast_websocket` solo lo intentaba con un loop corriendo en el
hilo actual: una ruta `def` (threadpool) NO tiene loop, así que el push se
saltaba en silencio y el aviso aparecía hasta recargar. Con las rutas de
TitulaTec en el threadpool (R7) eso afectaría a todas.

Ahora, sin loop en el hilo y con el loop principal registrado (el `lifespan` lo
guarda con `itcj2.utils.set_main_loop`, en todos los roles), el push se agenda
EN ese loop. Sin ninguno de los dos (CLI, Celery) no hace nada, como siempre.

Y `create` NO empuja al hacer el `flush`: deja el aviso en la sesión y lo
empuja cuando commitea la transacción RAÍZ (un SAVEPOINT liberado no cuenta),
o lo descarta si se revierte. Desde un hilo el push corre en el loop principal
EN PARALELO al hilo, así que empujar antes del commit dejaba al cliente (que
re-lee conteos y lista al recibir `notify`) con datos viejos, o con un toast
fantasma si la transacción se revertía.

El loop principal de la prueba corre en un hilo propio (`run_forever`), como el
de uvicorn corre mientras el threadpool trabaja. Las pruebas de `create` usan
la sesión transaccional real (`db_session`: SAVEPOINT sobre una transacción
externa que se revierte al final) y un usuario creado ahí.
"""
import asyncio
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import itcj2.utils
from itcj2.core.services.notification_service import NotificationService
from itcj2.observability.context import bind, current_request_id, reset

REQUEST_ID = "0123456789abcdef" * 2
WAIT = 5  # segundos; un push que sale tarda milisegundos
QUIET = 0.3  # segundos de espera para afirmar que NO salió un push


def _notification(**payload):
    return SimpleNamespace(to_dict=lambda: {"id": 7, **payload})


@pytest.fixture
def pushes(monkeypatch):
    """`push_notification` sustituido en su módulo (el servicio lo importa DENTRO
    de la función, así que ve el parche). Cada llamada anota el hilo, el
    `request_id` que ve y el payload; `done` avisa al hilo de la prueba."""
    import itcj2.sockets.notifications as notify_sockets

    seen = SimpleNamespace(calls=[], done=threading.Event())

    async def push_notification(user_id, payload):
        seen.calls.append({
            "user_id": user_id,
            "payload": payload,
            "thread": threading.get_ident(),
            "request_id": current_request_id(),
        })
        seen.done.set()

    monkeypatch.setattr(notify_sockets, "push_notification", push_notification)
    return seen


@pytest.fixture
def main_loop_thread(monkeypatch):
    """Un loop vivo en su propio hilo, registrado como loop principal."""
    loop = asyncio.new_event_loop()
    started = threading.Event()
    loop.call_soon(started.set)
    thread = threading.Thread(target=loop.run_forever, name="fake-main-loop", daemon=True)
    thread.start()
    assert started.wait(WAIT)
    monkeypatch.setattr(itcj2.utils, "_main_loop", loop)
    yield SimpleNamespace(loop=loop, thread=thread)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(WAIT)
    loop.close()


def _from_a_worker_thread(fn, *, request_id=None):
    """Corre `fn` en un hilo nativo, como el threadpool corre una ruta `def`
    (sin loop; con el `request_id` de la petición ya ligado si se pide)."""
    out = {}

    def run():
        out["thread"] = threading.get_ident()
        tokens = bind(request_id=request_id) if request_id else None
        try:
            fn()
        except BaseException as exc:  # lo que lanzara se vería en la prueba
            out["error"] = exc
        finally:
            if tokens is not None:
                reset(tokens)

    worker = threading.Thread(target=run, name="fake-threadpool-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive()
    return out


# ---------------------------------------------------------------------------
# broadcast_websocket: hilo sin loop + loop principal registrado
# ---------------------------------------------------------------------------

def test_from_a_worker_thread_the_push_is_scheduled_in_the_main_loop(main_loop_thread, pushes):
    worker = _from_a_worker_thread(
        lambda: NotificationService.broadcast_websocket(42, _notification(extra="x")),
    )

    assert "error" not in worker
    assert pushes.done.wait(WAIT), "el push no llegó al loop principal"
    [call] = pushes.calls
    assert call["user_id"] == 42
    assert call["payload"] == {"id": 7, "extra": "x"}
    # Corrió en el hilo del loop principal, no en el del que lo pidió.
    assert call["thread"] == main_loop_thread.thread.ident
    assert call["thread"] != worker["thread"]


def test_the_push_from_a_thread_carries_the_callers_request_id(main_loop_thread, pushes):
    _from_a_worker_thread(
        lambda: NotificationService.broadcast_websocket(42, _notification()),
        request_id=REQUEST_ID,
    )

    assert pushes.done.wait(WAIT)
    # El loop principal no tiene ningún `request_id`: si llega, vino del hilo.
    assert pushes.calls[0]["request_id"] == REQUEST_ID


def test_the_caller_does_not_wait_for_the_push(main_loop_thread, monkeypatch):
    """No se espera el resultado: un push lento no retrasa la respuesta."""
    import itcj2.sockets.notifications as notify_sockets

    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    async def slow_push(user_id, payload):
        started.set()
        await asyncio.get_running_loop().run_in_executor(None, release.wait, WAIT)
        finished.set()

    monkeypatch.setattr(notify_sockets, "push_notification", slow_push)
    try:
        worker = _from_a_worker_thread(
            lambda: NotificationService.broadcast_websocket(42, _notification()),
        )
        # `_from_a_worker_thread` ya volvió (el hilo terminó) con el push aún
        # sin acabar: nada lo estaba esperando.
        assert "error" not in worker
        assert started.wait(WAIT)
        assert not release.is_set()
    finally:
        release.set()
        # Que el push termine antes de parar el loop de la prueba.
        assert finished.wait(WAIT)


# ---------------------------------------------------------------------------
# Sin loop utilizable: no truena y no hace nada (CLI, Celery)
# ---------------------------------------------------------------------------

def _closed_loop():
    loop = asyncio.new_event_loop()
    loop.close()
    return loop


def _idle_loop():
    # Existe pero no corre (p. ej. un loop que ya paró).
    loop = asyncio.new_event_loop()
    return loop


@pytest.mark.parametrize(
    "make_main_loop",
    [lambda: None, _closed_loop, _idle_loop],
    ids=["sin-loop-registrado", "loop-cerrado", "loop-detenido"],
)
def test_without_a_usable_main_loop_it_does_not_raise_and_skips_the_push(
    monkeypatch, pushes, make_main_loop,
):
    loop = make_main_loop()
    monkeypatch.setattr(itcj2.utils, "_main_loop", loop)
    try:
        worker = _from_a_worker_thread(
            lambda: NotificationService.broadcast_websocket(42, _notification()),
        )
    finally:
        if loop is not None and not loop.is_closed():
            loop.close()

    assert "error" not in worker
    assert not pushes.done.wait(0.2)
    assert pushes.calls == []


def test_with_a_running_loop_in_this_thread_it_pushes_there_not_in_the_main_loop(
    main_loop_thread, pushes,
):
    async def main():
        NotificationService.broadcast_websocket(42, _notification())
        # Que corran las tareas pendientes de este loop.
        for _ in range(5):
            await asyncio.sleep(0)
        return threading.get_ident()

    this_thread = asyncio.run(main())

    [call] = pushes.calls
    assert call["thread"] == this_thread
    assert call["thread"] != main_loop_thread.thread.ident


# ---------------------------------------------------------------------------
# create(): el push espera al commit de la transacción RAÍZ
# ---------------------------------------------------------------------------

@pytest.fixture
def user(db_session):
    """Un usuario de verdad (FK de core_notifications), ya "commiteado" a la
    transacción externa de `db_session`: un `rollback()` de la prueba revierte
    solo lo que ella haga, no al usuario."""
    from itcj2.core.models.user import User

    u = User(first_name="PUSH", last_name="PRUEBA")
    db_session.add(u)
    db_session.flush()
    db_session.commit()
    return u


def _create(db, user, title="aviso"):
    return NotificationService.create(
        db, user_id=user.id, app_name="titulatec", type="PHASE_APPROVED", title=title,
    )


class _Gate:
    """El hilo trabajador se detiene en `checkpoint`; la prueba mira el estado
    (sin commit todavía) y lo suelta con `release`."""

    def __init__(self):
        self._reached = threading.Event()
        self._proceed = threading.Event()

    def checkpoint(self):
        self._reached.set()
        assert self._proceed.wait(WAIT)

    def wait_reached(self):
        assert self._reached.wait(WAIT), "el hilo no llegó al punto de control"

    def release(self):
        self._proceed.set()


def _run_gated(fn):
    """Corre `fn(gate)` en un hilo trabajador; devuelve (gate, resultado)."""
    gate = _Gate()
    out = {}

    def run():
        try:
            fn(gate)
        except BaseException as exc:
            out["error"] = exc
            gate._reached.set()  # no dejar a la prueba esperando

    worker = threading.Thread(target=run, name="fake-threadpool-worker")
    worker.start()
    out["worker"] = worker
    return gate, out


def _finish(gate, out):
    gate.release()
    out["worker"].join(WAIT)
    assert not out["worker"].is_alive()
    assert "error" not in out, out.get("error")


def test_create_from_a_thread_pushes_once_and_only_after_the_commit(
    db_session, user, main_loop_thread, pushes,
):
    made = {}

    def work(gate):
        made["n"] = _create(db_session, user, "tras el commit")
        gate.checkpoint()
        db_session.commit()
        db_session.commit()  # un segundo commit no vuelve a empujar

    gate, out = _run_gated(work)
    gate.wait_reached()
    # Con la fila ya en la sesión (flush) pero sin commit: nada se empuja.
    assert not pushes.done.wait(QUIET)
    assert pushes.calls == []

    _finish(gate, out)
    assert pushes.done.wait(WAIT)
    time.sleep(QUIET)  # y no llegan más
    [call] = pushes.calls
    assert call["user_id"] == user.id
    assert call["payload"]["id"] == made["n"].id
    assert call["payload"]["title"] == "tras el commit"
    assert call["thread"] == main_loop_thread.thread.ident


def test_create_in_a_running_loop_also_waits_for_the_commit(db_session, user, pushes):
    """Con loop en el hilo de la petición (endpoint `async`) el push también
    espera al commit, y sale ahí, por `spawn`."""

    async def main():
        _create(db_session, user, "en el loop")
        for _ in range(5):
            await asyncio.sleep(0)
        before_commit = list(pushes.calls)
        db_session.commit()
        for _ in range(5):
            await asyncio.sleep(0)
        return before_commit, threading.get_ident()

    before_commit, this_thread = asyncio.run(main())

    assert before_commit == []
    [call] = pushes.calls
    assert call["payload"]["title"] == "en el loop"
    assert call["thread"] == this_thread


def test_create_rolled_back_never_pushes(db_session, user, main_loop_thread, pushes):
    def work(gate):
        _create(db_session, user)
        db_session.rollback()
        gate.checkpoint()
        db_session.commit()  # una transacción vacía: nada que empujar

    gate, out = _run_gated(work)
    gate.wait_reached()
    _finish(gate, out)

    assert not pushes.done.wait(QUIET)
    assert pushes.calls == []


def test_a_released_savepoint_waits_for_the_outer_commit(
    db_session, user, main_loop_thread, pushes,
):
    """`mail_reminders` crea el aviso dentro de un SAVEPOINT por candidato: su
    liberación NO es el commit de la transacción."""

    def work(gate):
        with db_session.begin_nested():
            _create(db_session, user, "en un savepoint")
        gate.checkpoint()  # savepoint ya liberado, transacción raíz abierta
        db_session.commit()

    gate, out = _run_gated(work)
    gate.wait_reached()
    assert not pushes.done.wait(QUIET)
    assert pushes.calls == []

    _finish(gate, out)
    assert pushes.done.wait(WAIT)
    [call] = pushes.calls
    assert call["payload"]["title"] == "en un savepoint"


def test_a_rolled_back_savepoint_drops_only_its_own_pushes(
    db_session, user, main_loop_thread, pushes,
):
    def work(gate):
        _create(db_session, user, "antes")
        savepoint = db_session.begin_nested()
        _create(db_session, user, "dentro del savepoint")
        savepoint.rollback()
        _create(db_session, user, "despues")
        gate.checkpoint()
        db_session.commit()

    gate, out = _run_gated(work)
    gate.wait_reached()
    assert pushes.calls == []

    _finish(gate, out)
    assert pushes.done.wait(WAIT)
    time.sleep(QUIET)  # que no lleguen más
    titles = sorted(call["payload"]["title"] for call in pushes.calls)
    assert titles == ["antes", "despues"]


def test_a_released_inner_savepoint_dies_with_its_rolled_back_outer_one(
    db_session, user, main_loop_thread, pushes,
):
    def work(gate):
        outer = db_session.begin_nested()
        inner = db_session.begin_nested()
        _create(db_session, user, "en el interior")
        inner.commit()  # liberado: pasa a depender del exterior
        outer.rollback()
        _create(db_session, user, "el que queda")
        gate.checkpoint()
        db_session.commit()

    gate, out = _run_gated(work)
    gate.wait_reached()
    _finish(gate, out)

    assert pushes.done.wait(WAIT)
    time.sleep(QUIET)  # que no lleguen más
    assert [call["payload"]["title"] for call in pushes.calls] == ["el que queda"]


def test_a_session_closed_without_commit_does_not_leak_into_its_next_use(
    db_session, user, main_loop_thread, pushes,
):
    """Una sesión que nunca commitea (CLI en seco, rollback de `get_db` y
    `close()`) no deja avisos pendientes para la siguiente transacción."""

    def work(gate):
        _create(db_session, user, "huérfano")
        db_session.close()
        _create(db_session, user, "vigente")
        gate.checkpoint()
        db_session.commit()

    gate, out = _run_gated(work)
    gate.wait_reached()
    _finish(gate, out)

    assert pushes.done.wait(WAIT)
    time.sleep(QUIET)  # que no lleguen más
    assert [call["payload"]["title"] for call in pushes.calls] == ["vigente"]


def test_a_failing_emission_does_not_break_the_commit(
    db_session, user, main_loop_thread, pushes, monkeypatch, caplog,
):
    """El hook corre DENTRO de `commit()`: lo que falle ahí no puede salir
    como excepción de un commit que ya tuvo éxito."""

    def boom(*args, **kwargs):
        raise RuntimeError("Socket.IO caído")

    monkeypatch.setattr(NotificationService, "_emit_push", staticmethod(boom))

    def work(gate):
        _create(db_session, user)
        with caplog.at_level(logging.ERROR, logger="itcj2.core.services.notification_service"):
            db_session.commit()
        gate.checkpoint()

    gate, out = _run_gated(work)
    gate.wait_reached()
    _finish(gate, out)

    assert pushes.calls == []
    assert any("Socket.IO caído" in record.getMessage() for record in caplog.records)


def test_without_any_loop_nothing_is_serialized_or_queued(db_session, user, monkeypatch, pushes):
    """CLI y Celery: sin destino posible, `create` no arma el payload (que
    puede consultar estilos de app) ni deja nada pendiente."""
    from itcj2.core.models.notification import Notification

    monkeypatch.setattr(itcj2.utils, "_main_loop", None)
    to_dict = MagicMock(side_effect=AssertionError("to_dict no debía llamarse"))
    monkeypatch.setattr(Notification, "to_dict", to_dict)

    n = _create(db_session, user)
    db_session.commit()

    assert n.id is not None  # la notificación sí quedó en la sesión y se commiteó
    to_dict.assert_not_called()
    assert pushes.calls == []


def test_a_session_that_is_not_sqlalchemy_keeps_the_immediate_push(main_loop_thread, pushes):
    """Si `db` no es una `Session` (dobles de otras pruebas) no sabemos cuándo
    commitea: se empuja ya, como antes de R5."""
    db = MagicMock()
    stub = _notification(extra="y")

    with patch("itcj2.core.services.notification_service.Notification", return_value=stub):
        worker = _from_a_worker_thread(
            lambda: NotificationService.create(
                db, user_id=42, app_name="titulatec", type="PHASE_APPROVED", title="t",
            ),
        )

    assert "error" not in worker
    db.add.assert_called_once_with(stub)
    db.flush.assert_called_once_with()
    assert pushes.done.wait(WAIT)
    assert pushes.calls[0]["user_id"] == 42
    assert pushes.calls[0]["thread"] == main_loop_thread.thread.ident


def test_create_without_a_main_loop_still_saves_the_notification(monkeypatch, pushes):
    monkeypatch.setattr(itcj2.utils, "_main_loop", None)
    db = MagicMock()
    stub = _notification()

    with patch("itcj2.core.services.notification_service.Notification", return_value=stub):
        worker = _from_a_worker_thread(
            lambda: NotificationService.create(
                db, user_id=42, app_name="titulatec", type="X", title="t",
            ),
        )

    assert "error" not in worker
    db.add.assert_called_once_with(stub)
    db.flush.assert_called_once_with()
    assert pushes.calls == []


# ---------------------------------------------------------------------------
# Un solo emisor: nadie más empuja el aviso después de `create`
# ---------------------------------------------------------------------------

def test_no_app_or_core_module_pushes_the_notification_a_second_time():
    """Desde R5 `NotificationService.create` empuja el aviso también desde un
    hilo, así que el `_async_broadcast(push_notification(...))` a mano que
    agendatec ponía tras `create` en sus rutas `def` ya no suma: duplica el
    toast. Nadie en las apps ni en el core (salvo el propio servicio) llama
    `push_notification`; el relé de Redis lo llama desde `main.py`."""
    import ast
    import warnings
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "itcj2"
    service = root / "core" / "services" / "notification_service.py"
    files = sorted((root / "apps").rglob("*.py")) + sorted((root / "core").rglob("*.py"))
    offenders = []
    for path in files:
        if path == service:
            continue
        with warnings.catch_warnings():
            # Escapes viejos de otros módulos: ruido que no es de esta prueba.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            if "push_notification" in names:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")

    assert offenders == []
