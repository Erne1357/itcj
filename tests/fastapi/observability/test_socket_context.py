"""Instrumentación del tier de Socket.IO (plan Fase 5c).

Los handlers se invocan por el despacho REAL del `AsyncServer`
(`_trigger_event`, el mismo que usan `_handle_event` y `_handle_connect`), sin
red. Los contadores son de MÓDULO y acumulan entre tests: todo se mide como
DELTA con `REGISTRY.get_sample_value`, que exige el juego de etiquetas EXACTO.
"""
import logging

import pytest
import socketio
from prometheus_client import REGISTRY

from itcj2.observability import context
from itcj2.observability.logging_config import ContextFilter, JsonFormatter
from itcj2.observability.metrics import SOCKET_EVENT_DURATION, SOCKET_EVENTS
from itcj2.sockets.instrumentation import InstrumentedAsyncServer

pytestmark = pytest.mark.asyncio

EVENTS = "itcj_socket_events_total"
DURATION = "itcj_socket_event_duration_seconds_count"


def _count(namespace, event, status):
    return REGISTRY.get_sample_value(
        EVENTS, {"namespace": namespace, "event": event, "status": status}
    ) or 0.0


def _observed(namespace, event):
    return REGISTRY.get_sample_value(
        DURATION, {"namespace": namespace, "event": event}
    ) or 0.0


@pytest.fixture
def sio():
    return InstrumentedAsyncServer(async_mode="asgi")


class Boom(Exception):
    pass


async def test_cada_evento_acuna_su_propio_trace_id_y_no_filtra(sio):
    vistos = []
    sids = []

    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        vistos.append((context.current_trace_id(), context.current_request_id()))
        sids.append(context.current_sid())

    assert context.current_trace_id() == ""
    await sio._trigger_event("ping", "/slots", "s1")
    await sio._trigger_event("ping", "/slots", "s1")

    assert len(vistos) == 2
    for trace_id, request_id in vistos:
        assert len(trace_id) == 32 and request_id
    assert vistos[0][0] != vistos[1][0]
    assert context.current_trace_id() == ""
    assert context.current_request_id() == ""
    assert context.current_scope() is None
    assert sids == ["s1", "s1"]
    assert context.current_sid() == ""


async def test_user_id_de_la_sesion_llega_a_las_lineas_de_log(sio):
    visto = {}

    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", (), None)
        ContextFilter().filter(record)
        visto["user_id"] = getattr(record, "user_id", None)

    async def fake_get_session(sid, namespace=None):
        return {"user": {"sub": 42}}

    sio.get_session = fake_get_session
    await sio._trigger_event("ping", "/slots", "s1")
    assert visto["user_id"] == "42"


async def test_etiquetas_exactas_del_contador_y_del_histograma(sio):
    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        return None

    await sio._trigger_event("ping", "/slots", "s1")

    counter_labels = {
        tuple(sorted(s.labels)) for m in SOCKET_EVENTS.collect() for s in m.samples
    }
    hist_labels = {
        tuple(sorted(k for k in s.labels if k != "le"))
        for m in SOCKET_EVENT_DURATION.collect() for s in m.samples
    }
    assert counter_labels == {("event", "namespace", "status")}
    assert hist_labels == {("event", "namespace")}
    assert _count("/slots", "ping", "ok") >= 1


async def test_evento_y_namespace_desconocidos_colapsan_a_otro(sio):
    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        return None

    antes_evento = _count("/slots", "otro", "ok")
    antes_ns = _count("otro", "otro", "ok")

    resultado = await sio._trigger_event("nombre_inventado_por_un_cliente", "/slots", "s1")
    await sio._trigger_event("ping", "/no_existe", "s1")

    assert resultado is sio.not_handled
    assert _count("/slots", "otro", "ok") == antes_evento + 1
    assert _count("otro", "otro", "ok") == antes_ns + 1
    assert _count("/slots", "nombre_inventado_por_un_cliente", "ok") == 0


async def test_handler_que_lanza_cuenta_error_y_propaga(sio):
    @sio.on("falla", namespace="/maint")
    async def falla(sid):
        raise Boom("original")

    antes = _count("/maint", "falla", "error")
    with pytest.raises(Boom, match="original"):
        await sio._trigger_event("falla", "/maint", "s1")

    assert _count("/maint", "falla", "error") == antes + 1
    assert _observed("/maint", "falla") >= 1
    assert context.current_trace_id() == ""


async def test_valor_de_retorno_intacto(sio):
    @sio.on("dame", namespace="/notify")
    async def dame(sid, x):
        return {"ok": True, "x": x}

    assert await sio._trigger_event("dame", "/notify", "s1", 7) == {"ok": True, "x": 7}


async def test_rechazo_de_conexion_no_es_error_del_servidor(sio):
    @sio.on("connect", namespace="/system")
    async def on_connect(sid, environ):
        raise socketio.exceptions.ConnectionRefusedError("no")

    antes_ok = _count("/system", "connect", "ok")
    antes_err = _count("/system", "connect", "error")
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await sio._trigger_event("connect", "/system", "s1", {})

    assert _count("/system", "connect", "ok") == antes_ok + 1
    assert _count("/system", "connect", "error") == antes_err


async def test_firma_legacy_de_connect_no_cuenta_dos_veces(sio):
    # python-socketio prueba connect(sid, environ, auth) y, si da TypeError,
    # reintenta connect(sid, environ): el primer intento no es un evento.
    @sio.on("connect", namespace="/helpdesk")
    async def on_connect(sid, environ):
        return True

    antes_ok = _count("/helpdesk", "connect", "ok")
    antes_err = _count("/helpdesk", "connect", "error")
    with pytest.raises(TypeError):
        await sio._trigger_event("connect", "/helpdesk", "s1", {}, None)
    assert await sio._trigger_event("connect", "/helpdesk", "s1", {}) is True

    assert _count("/helpdesk", "connect", "ok") == antes_ok + 1
    assert _count("/helpdesk", "connect", "error") == antes_err


async def test_fallo_de_la_instrumentacion_no_impide_correr_el_handler(sio, monkeypatch):
    corrio = []

    @sio.on("ping", namespace="/requests")
    async def ping(sid):
        corrio.append(True)
        return "pong"

    def roto(*a, **k):
        raise RuntimeError("métrica rota")

    monkeypatch.setattr(SOCKET_EVENTS, "labels", roto)
    monkeypatch.setattr(SOCKET_EVENT_DURATION, "labels", roto)

    assert await sio._trigger_event("ping", "/requests", "s1") == "pong"
    assert corrio == [True]
    assert context.current_trace_id() == ""


async def test_la_linea_json_de_un_handler_lleva_el_sid(sio):
    import json

    lineas = []

    @sio.on("ping", namespace="/slots")
    async def ping(sid):
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", (), None)
        ContextFilter().filter(record)
        lineas.append(json.loads(JsonFormatter().format(record)))

    await sio._trigger_event("ping", "/slots", "sid-abc")

    assert lineas[0]["sid"] == "sid-abc"
    assert lineas[0]["trace_id"]
    # fuera del evento (HTTP, Celery) el campo existe y va vacío
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", (), None)
    ContextFilter().filter(record)
    assert json.loads(JsonFormatter().format(record))["sid"] == ""
