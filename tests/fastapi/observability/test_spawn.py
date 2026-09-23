"""`spawn()` y el broadcast descartado (plan Fase 5b, Task 4).

Hoy una corrutina fire-and-forget (`loop.create_task(...)` sin guardar la
tarea) falla de dos formas que no se ven: si revienta, su excepción solo sale
—sin `request_id` ni sitio— cuando el recolector destruye la tarea ("Task
exception was never retrieved"); y si queda suspendida sin que nadie la
referencie, el recolector la destruye A MEDIO VUELO (el loop solo guarda
referencias débiles a sus tareas). Y el broadcast que `async_broadcast`
descarta por falta de loop solo deja un warning, sin cuenta.

El contador es de MÓDULO y acumula entre tests: todo se mide como DELTA con
`REGISTRY.get_sample_value`, que exige el juego de etiquetas EXACTO (una
etiqueta de más o de menos daría `None` y el delta no cuadraría).

Sin BD ni datos sembrados.
"""
import asyncio
import gc
import io
import json
import logging
import threading
import warnings
import weakref
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

import itcj2.utils
from itcj2.observability import metrics, work
from itcj2.observability import spawn as spawn_mod
from itcj2.observability.context import bind, current_request_id, reset
from itcj2.observability.logging_config import ContextFilter, JsonFormatter
from itcj2.observability.spawn import spawn
from itcj2.utils import async_broadcast

TASKS = "itcj_background_tasks_total"
STATUSES = ("ok", "error", "dropped", "cancelled")

# El `request_id` de la petición que lanza la tarea.
ORIGIN = "0123456789abcdef" * 2


class ProbeBackgroundError(Exception):
    """Excepción propia: su nombre en `exc_type` prueba que sale el tipo REAL."""


def _counts(name: str) -> dict:
    return {
        status: REGISTRY.get_sample_value(TASKS, {"name": name, "status": status}) or 0.0
        for status in STATUSES
    }


def _delta(before: dict, after: dict) -> dict:
    return {status: after[status] - before[status] for status in STATUSES}


def _only(status: str, times: float = 1.0) -> dict:
    return {s: (times if s == status else 0.0) for s in STATUSES}


def _family_total() -> float:
    """Todo lo contado, sea cual sea la etiqueta: lo que no se contó bajo
    ningún `name`."""
    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == TASKS
    )


async def _settle() -> None:
    """Espera a que terminen las tareas de `spawn` de ESTE loop y a que
    corran sus done-callbacks."""
    loop = asyncio.get_running_loop()
    while True:
        pending = [t for t in list(spawn_mod._tasks) if t.get_loop() is loop]
        if not pending:
            return
        await asyncio.wait(pending)
        await asyncio.sleep(0)


def _capture_loop_errors(loop) -> list:
    """Lo que el loop mandaría a su manejador de excepciones ("Task exception
    was never retrieved", "Task was destroyed but it is pending!", un
    callback que lanza): apuntado en vez de impreso."""
    seen = []
    loop.set_exception_handler(lambda _loop, ctx: seen.append(ctx["message"]))
    return seen


@contextmanager
def _never_awaited():
    """Recoge los `RuntimeWarning: coroutine ... was never awaited` del
    bloque (el `gc.collect()` final destruye lo que haya quedado suelto)."""
    found = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield found
        finally:
            gc.collect()
            found.extend(
                str(w.message) for w in caught
                if issubclass(w.category, RuntimeWarning)
                and "never awaited" in str(w.message)
            )


@pytest.fixture
def spawn_log():
    """Las líneas que el handler REAL de producción (filtro de contexto +
    formateador JSON) escribe para el logger de `spawn`."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    spawn_mod.logger.addHandler(handler)
    try:
        yield lambda: buffer.getvalue().splitlines()
    finally:
        spawn_mod.logger.removeHandler(handler)


@pytest.fixture
def fresh_failure_log(monkeypatch):
    """El aviso de fallo de escritura va con límite de frecuencia GLOBAL: sin
    reiniciarlo, un test anterior que ya avisó dejaría mudo a este."""
    monkeypatch.setattr(work, "_last_failure_log", float("-inf"))


def _assert_origin_error_line(lines: list, name: str, coroutine: str, message: str):
    assert len(lines) == 1, lines
    line = lines[0]
    record = json.loads(line)  # la línea entera es UN objeto JSON
    assert record["level"] == "ERROR"
    assert record["request_id"] == ORIGIN
    assert name in record["msg"] and coroutine in record["msg"]
    assert record["exc_type"] == "ProbeBackgroundError"
    # El traceback completo, en una sola cadena: con el sitio del `raise`.
    assert record["exc_info"].startswith("Traceback")
    assert coroutine in record["exc_info"] and message in record["exc_info"]


# ---------------------------------------------------------------------------
# Contrato (global-constraints, "Contratos NUEVOS de la ronda 2")
# ---------------------------------------------------------------------------

def test_background_tasks_counter_matches_the_contract():
    counter = metrics.BACKGROUND_TASKS
    assert counter._type == "counter"
    # prometheus_client guarda el nombre sin `_total` y lo añade a la muestra.
    assert counter._name == "itcj_background_tasks"
    assert counter._labelnames == ("name", "status")


def test_closed_label_sets_match_the_contract():
    assert spawn_mod.BACKGROUND_TASK_NAMES == frozenset(
        {"async_broadcast", "notify_websocket_push"}
    )
    assert spawn_mod.BACKGROUND_TASK_STATUSES == frozenset(STATUSES)


# ---------------------------------------------------------------------------
# spawn(): ok / error / cancelled
# ---------------------------------------------------------------------------

def test_spawn_counts_ok_and_keeps_the_return_value():
    sentinel = object()

    async def job():
        await asyncio.sleep(0)
        return sentinel

    async def main():
        task = spawn(job(), name="async_broadcast")
        result = await task
        await _settle()
        return result

    before = _counts("async_broadcast")
    assert asyncio.run(main()) is sentinel
    assert _delta(before, _counts("async_broadcast")) == _only("ok")


def test_spawn_logs_the_exception_with_the_origin_request_id_and_counts_error(spawn_log):
    async def failing_job():
        await asyncio.sleep(0)
        # Dentro de la tarea el contexto es OTRO: la línea debe llevar el de
        # quien la lanzó, no lo que la tarea haya ligado.
        bind(request_id="f" * 32)
        raise ProbeBackgroundError("explota en segundo plano")

    async def main():
        loop_errors = _capture_loop_errors(asyncio.get_running_loop())
        tokens = bind(request_id=ORIGIN)
        task = spawn(failing_job(), name="notify_websocket_push")
        # La petición ya respondió (y reseteó sus ids) cuando la tarea falla.
        reset(tokens)
        # Fire-and-forget: nadie hace `await task` ni lee su excepción.
        await asyncio.wait([task])
        await asyncio.sleep(0)
        del task
        gc.collect()
        return loop_errors

    before = _counts("notify_websocket_push")
    loop_errors = asyncio.run(main())

    assert _delta(before, _counts("notify_websocket_push")) == _only("error")
    _assert_origin_error_line(
        spawn_log(), "notify_websocket_push", "failing_job", "explota en segundo plano"
    )
    # Sin "Task exception was never retrieved": ya se logueó una vez, con contexto.
    assert loop_errors == []


def test_a_cancelled_task_counts_cancelled_without_an_error_line(spawn_log):
    async def main():
        task = spawn(asyncio.sleep(3600), name="async_broadcast")
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait([task])
        await asyncio.sleep(0)

    before = _counts("async_broadcast")
    asyncio.run(main())

    assert _delta(before, _counts("async_broadcast")) == _only("cancelled")
    assert spawn_log() == []


def test_a_task_pending_at_loop_shutdown_counts_cancelled(spawn_log):
    """R38: el apagado del loop (un swap blue-green) cancela lo pendiente, y
    eso no debe caer en `error`."""
    async def main():
        spawn(asyncio.sleep(3600), name="async_broadcast")
        await asyncio.sleep(0)
        # `asyncio.run` cancela lo que siga vivo al salir, como el apagado.

    before = _counts("async_broadcast")
    asyncio.run(main())

    assert _delta(before, _counts("async_broadcast")) == _only("cancelled")
    assert spawn_log() == []


# ---------------------------------------------------------------------------
# spawn(): referencia fuerte mientras vuela, liberada al terminar
# ---------------------------------------------------------------------------

def _run_suspended_on_orphan_future(launch) -> dict:
    """Lanza con `launch(coro)` una corrutina suspendida en un futuro que solo
    ella referencia, recolecta a mitad de vuelo y luego la deja terminar si
    sobrevivió. Regresa lo observado."""
    async def main():
        loop = asyncio.get_running_loop()
        loop_errors = _capture_loop_errors(loop)
        holder = {}

        async def waits():
            future = loop.create_future()
            holder["future"] = weakref.ref(future)
            return await future

        baseline = len(spawn_mod._tasks)
        task_ref = weakref.ref(launch(waits()))
        await asyncio.sleep(0)  # arranca y queda suspendida en el futuro
        gc.collect()
        observed = {
            "alive_mid_flight": task_ref() is not None,
            "loop_errors": list(loop_errors),
        }
        future = holder["future"]()
        if future is not None:
            future.set_result("fin")
            del future
            await _settle()
        gc.collect()
        observed["released"] = task_ref() is None
        observed["set_back_to_baseline"] = len(spawn_mod._tasks) == baseline
        return observed

    return asyncio.run(main())


def test_spawn_keeps_the_task_alive_mid_flight_and_releases_it_when_done():
    observed = _run_suspended_on_orphan_future(
        lambda coro: spawn(coro, name="async_broadcast")
    )

    assert observed == {
        "alive_mid_flight": True,
        "loop_errors": [],
        "released": True,
        "set_back_to_baseline": True,
    }


def test_control_a_bare_create_task_is_collected_mid_flight():
    """Control positivo: sin `spawn`, el MISMO escenario pierde la tarea. Sin
    esto el test de arriba podría pasar porque el recolector no la tocaría de
    todos modos."""
    observed = _run_suspended_on_orphan_future(
        lambda coro: asyncio.get_running_loop().create_task(coro)
    )

    assert observed["alive_mid_flight"] is False
    assert observed["loop_errors"] == ["Task was destroyed but it is pending!"]


def test_the_strong_reference_set_does_not_grow(spawn_log):
    async def fails():
        raise ProbeBackgroundError("una de tantas")

    async def main():
        baseline = len(spawn_mod._tasks)
        tasks = []
        for _ in range(20):
            tasks.append(spawn(asyncio.sleep(0), name="async_broadcast"))
            tasks.append(spawn(fails(), name="async_broadcast"))
            tasks.append(spawn(asyncio.sleep(3600), name="async_broadcast"))
        assert len(spawn_mod._tasks) == baseline + 60
        await asyncio.sleep(0)
        for task in tasks[2::3]:
            task.cancel()
        await _settle()
        return baseline, len(spawn_mod._tasks)

    before = _counts("async_broadcast")
    baseline, after = asyncio.run(main())

    assert after == baseline
    assert _delta(before, _counts("async_broadcast")) == {
        "ok": 20.0, "error": 20.0, "dropped": 0.0, "cancelled": 20.0,
    }
    # Una línea por excepción; las canceladas no dejan ninguna.
    assert len(spawn_log()) == 20


# ---------------------------------------------------------------------------
# spawn(): la instrumentación nunca cambia el negocio (regla de oro 2)
# ---------------------------------------------------------------------------

def test_a_failing_counter_write_never_breaks_the_task(caplog, fresh_failure_log):
    async def job():
        return "hecho"

    async def main():
        loop_errors = _capture_loop_errors(asyncio.get_running_loop())
        results = [await spawn(job(), name="async_broadcast") for _ in range(2)]
        await _settle()
        return results, loop_errors

    failing = RuntimeError("mmap no se pudo crecer")
    with patch.object(metrics.BACKGROUND_TASKS, "labels", side_effect=failing):
        with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
            results, loop_errors = asyncio.run(main())

    assert results == ["hecho", "hecho"]
    # El done-callback no lanzó al loop ("Exception in callback ...").
    assert loop_errors == []
    failures = [r for r in caplog.records if "fallo al registrar" in r.getMessage()]
    assert len(failures) == 1  # dos fallos, un aviso (límite de frecuencia)


def test_spawn_without_a_running_loop_raises_and_closes_the_coroutine():
    async def job():
        pass

    with _never_awaited() as unawaited:
        coro = job()
        with pytest.raises(RuntimeError):
            spawn(coro, name="async_broadcast")
        assert coro.cr_frame is None  # cerrada: no va a correr
        del coro

    assert unawaited == []


def test_a_name_outside_the_closed_set_raises_in_strict_mode_and_closes_the_coroutine():
    ran = []

    async def job():
        ran.append(True)

    async def main():
        coro = job()
        with pytest.raises(ValueError, match="fuera del conjunto cerrado"):
            spawn(coro, name="broadcast_ticket_created")
        return coro.cr_frame is None

    with _never_awaited() as unawaited:
        assert asyncio.run(main()) is True

    assert ran == []
    assert unawaited == []


def test_a_name_outside_the_closed_set_in_production_runs_uncounted_and_warns_once(
    monkeypatch, caplog,
):
    monkeypatch.setattr(work, "strict_labels", lambda: False)
    monkeypatch.setattr(work, "_warned_labels", set())
    ran = []

    async def job():
        ran.append(True)

    async def main():
        for _ in range(2):
            await spawn(job(), name="broadcast_ticket_created")
        await _settle()

    before = _family_total()
    with caplog.at_level(logging.WARNING, logger="itcj2.observability"):
        asyncio.run(main())

    assert ran == [True, True]
    assert _family_total() == before  # una serie inventada rompería el presupuesto
    warned = [r for r in caplog.records if "fuera del conjunto cerrado" in r.getMessage()]
    assert len(warned) == 1


# ---------------------------------------------------------------------------
# async_broadcast
# ---------------------------------------------------------------------------

def _closed_loop():
    loop = asyncio.new_event_loop()
    loop.close()
    return loop


def _loop_closing_mid_call():
    # `is_running()` dijo que sí y el loop se cerró antes de programar (el
    # apagado): `call_soon_threadsafe` lanza "Event loop is closed". Función
    # y no MagicMock: el mock guardaría la corrutina en `call_args` y el
    # "never awaited" saldría después del test, no dentro.
    def call_soon_threadsafe(*args, **kwargs):
        raise RuntimeError("Event loop is closed")

    return SimpleNamespace(is_running=lambda: True, call_soon_threadsafe=call_soon_threadsafe)


@pytest.mark.parametrize(
    "make_main_loop",
    [lambda: None, _closed_loop, _loop_closing_mid_call],
    ids=["sin-loop", "loop-cerrado", "cierra-a-medio-camino"],
)
def test_async_broadcast_without_a_loop_counts_dropped_and_closes_the_coroutine(
    monkeypatch, caplog, make_main_loop,
):
    monkeypatch.setattr(itcj2.utils, "_main_loop", make_main_loop())
    ran = []

    async def broadcast_probe():
        ran.append(True)

    before = _counts("async_broadcast")
    with _never_awaited() as unawaited:
        with caplog.at_level(logging.WARNING, logger="itcj2.utils"):
            async_broadcast(broadcast_probe())

    assert ran == []
    assert _delta(before, _counts("async_broadcast")) == _only("dropped")
    # El warning de siempre se queda (lo que ya lee quien mire los logs).
    dropped = [r for r in caplog.records if "broadcast descartado" in r.getMessage()]
    assert len(dropped) == 1
    assert unawaited == []


async def _ok_probe():
    await asyncio.sleep(0)


async def failing_probe():
    await asyncio.sleep(0)
    raise ProbeBackgroundError("falla el broadcast")


def test_async_broadcast_inside_a_running_loop_goes_through_spawn(spawn_log):
    async def main():
        loop_errors = _capture_loop_errors(asyncio.get_running_loop())
        tokens = bind(request_id=ORIGIN)
        async_broadcast(_ok_probe())
        async_broadcast(failing_probe())
        reset(tokens)
        await _settle()
        gc.collect()
        return loop_errors

    before = _counts("async_broadcast")
    loop_errors = asyncio.run(main())

    assert _delta(before, _counts("async_broadcast")) == {
        "ok": 1.0, "error": 1.0, "dropped": 0.0, "cancelled": 0.0,
    }
    _assert_origin_error_line(
        spawn_log(), "async_broadcast", "failing_probe", "falla el broadcast"
    )
    assert loop_errors == []


def test_async_broadcast_from_a_thread_spawns_in_the_main_loop_with_the_callers_context(
    monkeypatch, spawn_log,
):
    """El camino de los endpoints `def`: sin loop en el hilo, la corrutina
    salta al loop principal. El `request_id` que llega es el del HILO que
    llama (el loop no tiene ninguno: si llega, vino de ahí) y el resultado se
    cuenta. El caso (f) de `test_context_propagation.py` lo prueba con un
    endpoint real."""
    seen = {}

    async def read_probe():
        seen["request_id"] = current_request_id()
        seen["thread"] = threading.get_ident()

    def sync_caller():
        # Un hilo nativo no hereda contexto: se liga aquí, como el threadpool
        # de anyio corre el endpoint con el de la petición.
        tokens = bind(request_id=ORIGIN)
        try:
            async_broadcast(read_probe())
            async_broadcast(failing_probe())
        finally:
            reset(tokens)

    async def main():
        loop = asyncio.get_running_loop()
        loop_errors = _capture_loop_errors(loop)
        monkeypatch.setattr(itcj2.utils, "_main_loop", loop)
        assert current_request_id() == ""
        caller = threading.Thread(target=sync_caller)
        caller.start()
        await asyncio.to_thread(caller.join)
        await _settle()
        gc.collect()
        return threading.get_ident(), loop_errors

    before = _counts("async_broadcast")
    loop_thread, loop_errors = asyncio.run(main())

    assert seen == {"request_id": ORIGIN, "thread": loop_thread}
    assert _delta(before, _counts("async_broadcast")) == {
        "ok": 1.0, "error": 1.0, "dropped": 0.0, "cancelled": 0.0,
    }
    _assert_origin_error_line(
        spawn_log(), "async_broadcast", "failing_probe", "falla el broadcast"
    )
    assert loop_errors == []


# ---------------------------------------------------------------------------
# NotificationService.broadcast_websocket (el `create_task` de :93)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_push(monkeypatch):
    """`push_notification` sustituido en su módulo: el servicio lo importa
    DENTRO de la función, así que ve el parche."""
    import itcj2.sockets.notifications as notify_sockets

    calls = []

    async def push_notification(user_id, payload):
        await asyncio.sleep(0)
        calls.append((user_id, payload))
        if payload.get("explota"):
            raise ProbeBackgroundError("Redis caído")

    monkeypatch.setattr(notify_sockets, "push_notification", push_notification)
    return calls


def _notification(**payload):
    return SimpleNamespace(to_dict=lambda: {"id": 7, **payload})


def test_broadcast_websocket_counts_the_push(fake_push):
    from itcj2.core.services.notification_service import NotificationService

    async def main():
        NotificationService.broadcast_websocket(42, _notification())
        await _settle()

    before = _counts("notify_websocket_push")
    asyncio.run(main())

    assert fake_push == [(42, {"id": 7})]
    assert _delta(before, _counts("notify_websocket_push")) == _only("ok")


def test_a_failing_push_is_logged_with_the_origin_request_id(fake_push, spawn_log):
    """Hoy esta excepción se la traga `notification_service.py:93`."""
    from itcj2.core.services.notification_service import NotificationService

    async def main():
        loop_errors = _capture_loop_errors(asyncio.get_running_loop())
        tokens = bind(request_id=ORIGIN)
        NotificationService.broadcast_websocket(42, _notification(explota=True))
        reset(tokens)
        await _settle()
        gc.collect()
        return loop_errors

    before = _counts("notify_websocket_push")
    loop_errors = asyncio.run(main())

    assert _delta(before, _counts("notify_websocket_push")) == _only("error")
    _assert_origin_error_line(
        spawn_log(), "notify_websocket_push", "push_notification", "Redis caído"
    )
    assert loop_errors == []


def test_broadcast_websocket_without_a_loop_still_skips_the_push(fake_push):
    """Fuera de un loop (un servicio `def` en el threadpool) el push no se
    intenta, como hasta hoy: ni se crea la corrutina ni se cuenta nada."""
    from itcj2.core.services.notification_service import NotificationService

    before = _family_total()
    with _never_awaited() as unawaited:
        NotificationService.broadcast_websocket(42, _notification())

    assert fake_push == []
    assert _family_total() == before
    assert unawaited == []
