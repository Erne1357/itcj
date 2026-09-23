"""Sonda de lag del event loop (plan Fase 3, test 2).

El histograma es de módulo y acumula entre tests: todo se mide como DELTA.
Cada escenario corre en su propio loop (`asyncio.run`) y termina cancelando
la sonda y esperándola, como el `lifespan`.
"""
import asyncio
import logging
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from itcj2.observability import loop_lag, metrics, saturation
from tests.conftest import TEST_SECRET

LAG = "itcj_event_loop_lag_seconds"


def _count() -> float:
    return REGISTRY.get_sample_value(f"{LAG}_count") or 0.0


def _at_or_below(le: str) -> float:
    return REGISTRY.get_sample_value(f"{LAG}_bucket", {"le": le}) or 0.0


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


def test_lag_histogram_matches_the_contract():
    assert metrics.EVENT_LOOP_LAG._name == LAG
    assert metrics.EVENT_LOOP_LAG._labelnames == ()
    assert metrics.EVENT_LOOP_LAG._upper_bounds == [
        0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, float("inf"),
    ]


def test_saturation_refresh_is_about_every_five_seconds():
    assert loop_lag.LAG_INTERVAL_SECONDS == 0.25
    assert 5 <= loop_lag.LAG_INTERVAL_SECONDS * loop_lag.SATURATION_EVERY <= 10


def test_blocking_the_loop_lands_an_observation_above_100ms():
    over_before = _count() - _at_or_below("0.1")

    async def _scenario():
        # Intervalo corto a propósito: con el de 0,25 s lo que se observa es
        # el bloqueo MENOS lo que ya iba a dormir la sonda, y el resultado
        # dependería de en qué punto de su sueño cae el `time.sleep`.
        with patch.object(saturation, "update_gauges"):
            task = asyncio.create_task(loop_lag.run_probe(interval=0.02))
            await asyncio.sleep(0.05)
            time.sleep(0.3)  # I/O síncrono en una corrutina: bloquea el loop.
            await asyncio.sleep(0.1)
            await _stop(task)

    asyncio.run(_scenario())

    assert _count() - _at_or_below("0.1") - over_before >= 1


def test_saturation_refresh_rides_the_lag_probe():
    # Sin segundo temporizador: `update_gauges()` corre DENTRO de la tarea
    # de la sonda, una vez cada `saturation_every` observaciones de lag.
    calls = []

    def _record():
        calls.append((asyncio.current_task(), _count()))

    async def _scenario():
        with patch.object(saturation, "update_gauges", side_effect=_record):
            task = asyncio.create_task(
                loop_lag.run_probe(interval=0.001, saturation_every=4)
            )
            deadline = time.monotonic() + 5
            while len(calls) < 3:
                assert time.monotonic() < deadline, "la sonda no refrescó"
                await asyncio.sleep(0.005)
            await _stop(task)
        return task

    task = asyncio.run(_scenario())

    assert all(caller is task for caller, _ in calls)
    counts = [count for _, count in calls]
    assert counts[1] - counts[0] == 4
    assert counts[2] - counts[1] == 4


def test_a_failing_cycle_does_not_kill_the_probe(caplog):
    calls = []

    def _explode_once():
        calls.append(None)
        if len(calls) == 1:
            raise RuntimeError("ciclo roto")

    async def _scenario():
        with patch.object(saturation, "update_gauges", side_effect=_explode_once):
            task = asyncio.create_task(
                loop_lag.run_probe(interval=0.001, saturation_every=1)
            )
            deadline = time.monotonic() + 5
            while len(calls) < 3:
                assert time.monotonic() < deadline, "la sonda murió"
                await asyncio.sleep(0.005)
            assert not task.done()
            await _stop(task)

    with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
        asyncio.run(_scenario())

    assert any(
        r.exc_info and "ciclo roto" in str(r.exc_info[1]) for r in caplog.records
    )


def test_lifespan_runs_the_probe_and_stops_it_before_dispose():
    from itcj2 import database

    seen = {}
    real_dispose = database.engine.dispose

    def _dispose(*args, **kwargs):
        # La sonda lee `engine.pool`: tiene que estar parada antes de esto.
        seen["probe_done_at_dispose"] = seen["probe"].done()
        return real_dispose(*args, **kwargs)

    async def _probe_task():
        return next(
            t for t in asyncio.all_tasks() if t.get_name() == loop_lag.PROBE_TASK_NAME
        )

    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET), patch.object(
        database.engine, "dispose", side_effect=_dispose
    ):
        from itcj2.main import create_app

        with TestClient(create_app()) as client:
            seen["probe"] = client.portal.call(_probe_task)
            assert not seen["probe"].done()

    assert seen["probe_done_at_dispose"] is True
    assert seen["probe"].cancelled()
