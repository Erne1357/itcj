"""Sonda de saturación (plan Fase 3, test 1): pool de BD, limiter de anyio y
executor por defecto de asyncio.

Cada ciclo (`update_gauges()`) corre DENTRO de un event loop (`_cycle()`),
igual que en producción, donde lo llama la sonda de lag: fuera de un loop
`anyio.to_thread.current_default_thread_limiter()` lanza `NoEventLoopError`.

Los Gauges son de módulo pero se escriben con `.set()`: tras un ciclo valen
lo de ESE ciclo, así que se comparan en absoluto contra la fuente, sin deltas.

BD: el engine REAL de `itcj2.database` (el que lee la sonda). Sin datos: solo
se prestan conexiones, así que vale igual contra la base vacía de CI.
"""
import asyncio
import logging
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, Gauge

from itcj2 import database
from itcj2.config import get_settings
from itcj2.observability import metrics, saturation
from tests.conftest import TEST_SECRET
from tests.fastapi.infra.test_compose_prod_invariants import ASYNCIO_EXECUTOR_CEILING

SATURATION_GAUGES = {
    "itcj_anyio_threadpool_total",
    "itcj_anyio_threadpool_borrowed",
    "itcj_anyio_threadpool_waiting",
    "itcj_asyncio_threadpool_total",
    "itcj_asyncio_threadpool_threads",
    "itcj_asyncio_threadpool_waiting",
    "itcj_db_pool_size",
    "itcj_db_pool_checkedin",
    "itcj_db_pool_checkedout",
    "itcj_db_pool_overflow",
    "itcj_db_pool_max_overflow",
}


def _gauge(name: str) -> float | None:
    return REGISTRY.get_sample_value(name)


def _cycle() -> None:
    """Un ciclo de la sonda, dentro de un loop nuevo."""

    async def _in_loop():
        saturation.update_gauges()

    asyncio.run(_in_loop())


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("la condición no se cumplió a tiempo")
        time.sleep(0.005)


# ---------------------------------------------------------------------------
# Declaración
# ---------------------------------------------------------------------------
def test_saturation_gauges_are_real_livesum_gauges():
    # El test que impide reescribirlos como colector personalizado: un
    # colector corre solo en el worker que atiende el scrape y publicaría el
    # pool de 1 de los 4 workers, al azar (plan Fase 3, "por qué no un
    # colector"). `livesum` es lo que suma los 4 ficheros mmap.
    declared = {
        obj._name: obj
        for obj in vars(metrics).values()
        if isinstance(obj, Gauge) and obj._name in SATURATION_GAUGES
    }

    assert set(declared) == SATURATION_GAUGES
    for name, gauge in declared.items():
        assert gauge._multiprocess_mode == "livesum", name
        assert gauge._labelnames == (), name


# ---------------------------------------------------------------------------
# Pool de BD
# ---------------------------------------------------------------------------
def test_checked_out_connections_move_the_pool_gauges():
    held = [database.engine.connect() for _ in range(3)]
    try:
        _cycle()
        pool = database.engine.pool
        with_held = _gauge("itcj_db_pool_checkedout")
        assert with_held == pool.checkedout()
        assert with_held >= 3
        assert _gauge("itcj_db_pool_size") == pool.size()
        assert _gauge("itcj_db_pool_checkedin") == pool.checkedin()
        assert _gauge("itcj_db_pool_overflow") == pool.overflow()
    finally:
        for conn in held:
            conn.close()

    _cycle()
    assert _gauge("itcj_db_pool_checkedout") == with_held - 3


def test_max_overflow_comes_from_settings(monkeypatch):
    # No de `pool._max_overflow` (privado) ni de `overflow()` (arranca en
    # -pool_size, plan §9.12): de la configuración que dimensiona el pool.
    monkeypatch.setattr(get_settings(), "DB_MAX_OVERFLOW", 7)

    _cycle()

    assert _gauge("itcj_db_pool_max_overflow") == 7


def test_cycle_after_dispose_reads_the_new_pool(caplog):
    # `dispose()` (apagado, respawn) cambia la identidad de `engine.pool`, y
    # leer una referencia vieja NUNCA falla: se congela. Por eso el "no
    # lanza" no basta; hace falta ver los números del pool nuevo.
    old_pool = database.engine.pool
    database.engine.dispose()
    assert database.engine.pool is not old_pool

    with caplog.at_level(logging.WARNING, logger="itcj2.observability"):
        _cycle()
    # Solo los de la sonda: caplog también recoge WARNING de cualquier otro
    # logger (SQLAlchemy al disponer el pool, p. ej.) y no son de este test.
    assert not [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith("itcj2.observability")
    ]

    held_new = [database.engine.connect() for _ in range(2)]
    try:
        _cycle()
        fresh = database.engine.pool.checkedout()
        assert fresh == 2
        assert _gauge("itcj_db_pool_checkedout") == fresh
        # Una referencia cacheada del pool viejo se quedó en su reposo:
        assert old_pool.checkedout() == 0
    finally:
        for conn in held_new:
            conn.close()


# ---------------------------------------------------------------------------
# Limiter de anyio (endpoints `def`)
# ---------------------------------------------------------------------------
def test_anyio_limiter_waiting_is_exported():
    limiter = SimpleNamespace(
        total_tokens=40,
        borrowed_tokens=40,
        statistics=lambda: SimpleNamespace(tasks_waiting=7),
    )
    with patch("anyio.to_thread.current_default_thread_limiter", return_value=limiter):
        _cycle()

    assert _gauge("itcj_anyio_threadpool_total") == 40
    assert _gauge("itcj_anyio_threadpool_borrowed") == 40
    assert _gauge("itcj_anyio_threadpool_waiting") == 7


def test_anyio_real_limiter_reports_a_borrowed_thread():
    import anyio.to_thread

    release = threading.Event()
    running = threading.Event()

    def _blocking():
        running.set()
        release.wait(5)

    async def _scenario():
        worker = asyncio.create_task(anyio.to_thread.run_sync(_blocking))
        try:
            while not running.is_set():
                await asyncio.sleep(0.005)
            saturation.update_gauges()
            return anyio.to_thread.current_default_thread_limiter().total_tokens
        finally:
            release.set()
            await worker

    total = asyncio.run(_scenario())

    assert _gauge("itcj_anyio_threadpool_total") == total
    assert _gauge("itcj_anyio_threadpool_borrowed") == 1
    assert _gauge("itcj_anyio_threadpool_waiting") == 0


def test_a_failing_source_is_logged_and_the_others_still_update(caplog):
    # Un ciclo nunca lanza (mataría la tarea y los Gauges se congelarían sin
    # aviso), y una fuente rota no deja sin actualizar a las demás.
    held = database.engine.connect()
    try:
        with patch(
            "anyio.to_thread.current_default_thread_limiter",
            side_effect=RuntimeError("limiter roto"),
        ), caplog.at_level(logging.ERROR, logger="itcj2.observability"):
            _cycle()

        assert _gauge("itcj_db_pool_checkedout") == database.engine.pool.checkedout()
        assert any(
            r.exc_info and "limiter roto" in str(r.exc_info[1]) for r in caplog.records
        )
    finally:
        held.close()


# ---------------------------------------------------------------------------
# Executor por defecto de asyncio (`asyncio.to_thread`, tier sockets)
# ---------------------------------------------------------------------------
def test_installed_executor_keeps_the_default_sizing():
    # R7: sin `max_workers`, el mismo min(32, cpu+4) que el default; el
    # invariante del compose de prod (pool+overflow de sockets >= techo del
    # executor) sigue valiendo.
    async def _scenario():
        loop = asyncio.get_running_loop()
        executor = saturation.install_default_executor(loop)
        name = await asyncio.to_thread(lambda: threading.current_thread().name)
        return executor, name

    executor, thread_name = asyncio.run(_scenario())

    assert saturation._default_executor is executor
    assert executor._max_workers == min(32, (os.cpu_count() or 1) + 4)
    assert executor._max_workers <= ASYNCIO_EXECUTOR_CEILING
    # `asyncio.to_thread` pasa por la instancia instalada.
    assert thread_name.startswith("itcj-default")


def test_busy_default_executor_moves_waiting_and_threads():
    release = threading.Event()
    started = []
    queued_beyond_capacity = 3

    def _blocking():
        started.append(threading.current_thread().name)
        release.wait(5)

    async def _scenario():
        loop = asyncio.get_running_loop()
        executor = saturation.install_default_executor(loop)
        workers = executor._max_workers
        futures = [
            loop.run_in_executor(None, _blocking)
            for _ in range(workers + queued_beyond_capacity)
        ]
        try:
            deadline = time.monotonic() + 5
            while len(started) < workers:
                assert time.monotonic() < deadline, "el executor no se llenó"
                await asyncio.sleep(0.005)
            saturation.update_gauges()
            busy = {
                "total": _gauge("itcj_asyncio_threadpool_total"),
                "threads": _gauge("itcj_asyncio_threadpool_threads"),
                "waiting": _gauge("itcj_asyncio_threadpool_waiting"),
            }
        finally:
            release.set()
            await asyncio.gather(*futures)
        saturation.update_gauges()
        return workers, busy

    workers, busy = asyncio.run(_scenario())

    assert busy == {
        "total": workers,
        "threads": workers,
        "waiting": queued_beyond_capacity,
    }
    assert _gauge("itcj_asyncio_threadpool_waiting") == 0
    # ThreadPoolExecutor nunca retira hilos: `threads` es la marca más alta.
    assert _gauge("itcj_asyncio_threadpool_threads") == workers


def test_lifespan_installs_the_default_executor():
    async def _default_executor_thread():
        return await asyncio.to_thread(threading.current_thread)

    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        with TestClient(create_app()) as client:
            thread = client.portal.call(_default_executor_thread)

    assert thread.name.startswith("itcj-default")
    # El loop del TestClient cerró y apagó su executor: sin hilos colgados.
    _wait_until(lambda: not thread.is_alive())
