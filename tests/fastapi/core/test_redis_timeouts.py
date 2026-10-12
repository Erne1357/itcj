"""Los clientes Redis de la app no pueden colgarse con un Redis «agujero negro».

Un Redis que acepta la conexión TCP y nunca responde (red partida sin RST,
proceso congelado) dejaba cada operación esperando para siempre: autenticación
colgada en cada petición con `sv`, holds de AgendaTec colgados. Con
`socket_timeout` la operación lanza y los caminos fail-open existentes toman el
relevo. El reverso: ese timeout NO debe aplicarse al suscriptor de pub/sub, que
bloquea legítimamente esperando mensajes.
"""
import asyncio
import socket
import threading
import time

import pytest
import redis
import redis.asyncio as aioredis

from itcj2.core.services import session_service as ss
from itcj2.core.utils import redis_conn, redis_conn_async


@pytest.fixture
def blackhole(monkeypatch):
    """Socket que acepta conexiones y jamás contesta; apunta los clientes a él."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    conns = []
    stop = threading.Event()

    def _accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conns.append(srv.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    port = srv.getsockname()[1]
    monkeypatch.setattr(redis_conn, "REDIS_URL", f"redis://127.0.0.1:{port}/0")
    monkeypatch.setattr(redis_conn, "_redis", None)
    redis_conn_async._clients.clear()
    yield port
    stop.set()
    t.join()
    for c in conns:
        c.close()
    srv.close()
    redis_conn._redis = None
    redis_conn_async._clients.clear()


def test_timeouts_por_defecto():
    assert redis_conn.REDIS_SOCKET_CONNECT_TIMEOUT == 1
    assert redis_conn.REDIS_SOCKET_TIMEOUT == 2


def test_sync_client_falla_en_segundos_no_se_cuelga(blackhole):
    t0 = time.monotonic()
    with pytest.raises(redis.exceptions.TimeoutError):
        redis_conn.get_redis().get("k")
    assert time.monotonic() - t0 < 4


def test_current_version_failopen_con_redis_agujero_negro(blackhole, monkeypatch):
    monkeypatch.setattr(ss, "_read_epoch_from_db", lambda uid: None)
    t0 = time.monotonic()
    assert ss.current_version(1234567) is None
    assert time.monotonic() - t0 < 4


def test_current_version_async_failopen_con_redis_agujero_negro(blackhole, monkeypatch):
    monkeypatch.setattr(ss, "_read_epoch_from_db", lambda uid: None)

    async def _run():
        t0 = time.monotonic()
        assert await ss.current_version_async(1234567) is None
        assert time.monotonic() - t0 < 4

    asyncio.run(_run())


def test_async_client_falla_en_segundos_no_se_cuelga(blackhole):
    async def _run():
        t0 = time.monotonic()
        with pytest.raises(redis.exceptions.TimeoutError):
            await redis_conn_async.get_redis_async().get("k")
        assert time.monotonic() - t0 < 4

    asyncio.run(_run())


def test_suscriptor_pubsub_escucha_mas_de_2s_sin_error():
    """El suscriptor de main.py crea su PROPIO cliente (no el compartido), así que
    el socket_timeout de la app no le aplica. Si alguien lo migrara al cliente
    compartido, `listen()` lanzaría TimeoutError a los 2 s sin tráfico."""
    import inspect

    from itcj2 import main

    src = inspect.getsource(main._redis_task_subscriber)
    assert "get_redis_async()" not in src
    assert "aioredis.from_url(settings.REDIS_URL)" in src

    async def _run():
        r = aioredis.from_url(redis_conn.REDIS_URL, decode_responses=True)
        try:
            async with r.pubsub() as ps:
                await ps.subscribe("t3_no_traffic")

                async def _listen():
                    async for _ in ps.listen():
                        pass

                task = asyncio.create_task(_listen())
                await asyncio.sleep(3)
                assert not task.done(), "listen() terminó/falló antes de 3 s"
                task.cancel()
        finally:
            await r.aclose()

    asyncio.run(_run())
