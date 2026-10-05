"""El push de Socket.IO de una notificación también sale desde un hilo.

Plan de rendimiento de TitulaTec, R5 (spec §3.6). `NotificationService.create`
siempre guarda la notificación en BD; lo que va aparte es el push en tiempo
real. Antes, `broadcast_websocket` solo lo intentaba con un loop corriendo en el
hilo actual: una ruta `def` (threadpool) NO tiene loop, así que el push se
saltaba en silencio y el aviso aparecía hasta recargar. Con las rutas de
TitulaTec en el threadpool (R7) eso afectaría a todas.

Ahora, sin loop en el hilo y con el loop principal registrado (el `lifespan` lo
guarda con `itcj2.utils.set_main_loop`, en todos los roles), el push se agenda
EN ese loop. Sin ninguno de los dos (CLI, Celery) no hace nada, como siempre.

El loop principal de la prueba corre en un hilo propio (`run_forever`), como el
de uvicorn corre mientras el threadpool trabaja. Sin BD: la sesión es un
`MagicMock` y la notificación un doble con `to_dict`.
"""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import itcj2.utils
from itcj2.core.services.notification_service import NotificationService
from itcj2.observability.context import bind, current_request_id, reset

REQUEST_ID = "0123456789abcdef" * 2
WAIT = 5  # segundos; un push que sale tarda milisegundos


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
# Hilo sin loop + loop principal registrado: el push se agenda en ese loop
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


def test_create_from_a_thread_saves_the_row_and_schedules_the_push(main_loop_thread, pushes):
    """`create` es lo que llama TitulaTec (`notify_student`): fila en la sesión
    y push, sin que el hilo espere al push."""
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
# Loop corriendo en el hilo actual: como hoy, en ESE loop
# ---------------------------------------------------------------------------

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
# Un solo emisor: nadie más empuja el aviso después de `create`
# ---------------------------------------------------------------------------

def test_no_app_pushes_the_notification_a_second_time():
    """Desde R5 `NotificationService.create` empuja el aviso también desde un
    hilo, así que el `_async_broadcast(push_notification(...))` a mano que
    agendatec ponía tras `create` en sus rutas `def` ya no suma: duplica el
    toast. El único que debe llamar `push_notification` en las apps es nadie
    (el core lo llama desde el servicio; el relé de Redis, desde `main.py`)."""
    import ast
    import warnings
    from pathlib import Path

    apps = Path(__file__).resolve().parents[3] / "itcj2" / "apps"
    offenders = []
    for path in sorted(apps.rglob("*.py")):
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
                offenders.append(f"{path.relative_to(apps.parent.parent)}:{node.lineno}")

    assert offenders == []
