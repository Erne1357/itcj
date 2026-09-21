"""Tests de `itcj2.observability.context`.

Ver el brief: .superpowers/sdd/2026-09-21-obs-f0-f3/task-2-brief.md

No dependen de BD ni de datos sembrados (corren igual en la base vacía de CI):
son primitivas puras de contextvars/threading/regex.
"""
import re
import threading
from asyncio import gather, run as asyncio_run, sleep

import pytest

from itcj2.observability import context

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# new_ids()
# ---------------------------------------------------------------------------

def test_new_ids_have_w3c_shape():
    trace_id, span_id = context.new_ids()
    assert _HEX32.match(trace_id), f"trace_id no es 32-hex minusculas: {trace_id!r}"
    assert _HEX16.match(span_id), f"span_id no es 16-hex minusculas: {span_id!r}"


def test_new_ids_are_not_repeated():
    # Guardián barato de que no se está devolviendo una constante: si algún
    # día `new_ids()` dejara de usar una fuente aleatoria, todas las
    # peticiones concurrentes compartirían trace_id y la correlación en
    # Tempo/Loki dejaría de servir para distinguir peticiones.
    ids = {context.new_ids() for _ in range(20)}
    assert len(ids) == 20


# ---------------------------------------------------------------------------
# bind() aislado entre asyncio.Task concurrentes
# ---------------------------------------------------------------------------

def test_bind_is_isolated_between_concurrent_tasks():
    results = {}

    async def worker(name, trace_id):
        tokens = context.bind(trace_id=trace_id)
        try:
            # El sleep deja el hueco donde, si bind() compartiera estado
            # entre tasks (p.ej. una variable global en vez de un
            # ContextVar), esta lectura vería el trace_id de la OTRA task
            # que corrió mientras esta dormía.
            await sleep(0.01)
            results[name] = context.current_trace_id()
        finally:
            context.reset(tokens)

    async def main():
        await gather(worker("a", "a" * 32), worker("b", "b" * 32))

    asyncio_run(main())
    assert results == {"a": "a" * 32, "b": "b" * 32}


# ---------------------------------------------------------------------------
# snapshot()/restore() ida y vuelta en un threading.Thread desnudo
# ---------------------------------------------------------------------------

def test_snapshot_restore_round_trip_in_bare_thread():
    tokens = context.bind(trace_id="c" * 32, span_id="d" * 16, request_id="e" * 32)
    try:
        snap = context.snapshot()
    finally:
        context.reset(tokens)

    seen = {}

    def target():
        with context.restore(snap):
            seen["trace_id"] = context.current_trace_id()
            seen["span_id"] = context.current_span_id()
            seen["request_id"] = context.current_request_id()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()

    assert seen == {"trace_id": "c" * 32, "span_id": "d" * 16, "request_id": "e" * 32}


def test_bare_thread_has_no_context_without_restore():
    # Un hilo nativo NO hereda los ContextVars del hilo que lo crea (a
    # diferencia de una asyncio.Task, que sí copia el Context al nacer). Sin
    # restore(), current_*() debe caer al valor por defecto, no reventar.
    seen = {}

    def target():
        seen["trace_id"] = context.current_trace_id()
        seen["request_id"] = context.current_request_id()

    tokens = context.bind(trace_id="f" * 32, request_id="1" * 32)
    try:
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
    finally:
        context.reset(tokens)

    assert seen == {"trace_id": "", "request_id": ""}


def test_restore_tolerates_none_snapshot():
    with context.restore(None):
        assert context.current_trace_id() == ""
        assert context.current_span_id() == ""
        assert context.current_request_id() == ""


def test_restore_tolerates_partial_snapshot():
    with context.restore({"trace_id": "2" * 32}):
        assert context.current_trace_id() == "2" * 32
        assert context.current_span_id() == ""


# ---------------------------------------------------------------------------
# current_trace_id(): ContextVar cuando OTel no está importable
# ---------------------------------------------------------------------------

def test_current_trace_id_falls_back_to_contextvar_without_otel(monkeypatch):
    # El import de OTel se resuelve UNA vez al cargar el módulo, no en cada
    # llamada a current_trace_id() (fix de review T2 R0: un import fallido no
    # se cachea en sys.modules y repetirlo en cada llamada costaba ~800
    # us/llamada). Por eso ya no sirve forzar ImportError vía sys.modules:
    # hay que parchear directo el atributo cacheado.
    monkeypatch.setattr(context, "_otel_trace", None)

    tokens = context.bind(trace_id="3" * 32)
    try:
        assert context.current_trace_id() == "3" * 32
    finally:
        context.reset(tokens)


def test_current_trace_id_prefers_valid_otel_span(monkeypatch):
    # Contraparte del test anterior: si OTel SÍ es importable y hay un span
    # válido, gana sobre el ContextVar (drop-in para la Fase 7).
    class _FakeSpanContext:
        is_valid = True
        trace_id = int("4" * 32, 16)

    class _FakeSpan:
        def get_span_context(self):
            return _FakeSpanContext()

    class _FakeTraceModule:
        @staticmethod
        def get_current_span():
            return _FakeSpan()

    # Mismo motivo que en el test anterior: `_otel_trace` ya está resuelto
    # al importar el módulo, así que se parchea directo en vez de simular el
    # import vía sys.modules (que ya no tiene ningún efecto en
    # current_trace_id()).
    monkeypatch.setattr(context, "_otel_trace", _FakeTraceModule)

    tokens = context.bind(trace_id="5" * 32)
    try:
        assert context.current_trace_id() == "4" * 32
    finally:
        context.reset(tokens)


# ---------------------------------------------------------------------------
# parse_traceparent()
# ---------------------------------------------------------------------------

def test_parse_traceparent_accepts_valid():
    value = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert context.parse_traceparent(value) == ("a" * 32, "b" * 16)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "01-" + "a" * 32 + "-" + "b" * 16 + "-01",  # versión rara (no "00")
        "ff-" + "a" * 32 + "-" + "b" * 16 + "-01",  # versión reservada
        "00-" + "a" * 31 + "-" + "b" * 16 + "-01",  # trace_id corto
        "00-" + "a" * 33 + "-" + "b" * 16 + "-01",  # trace_id largo
        "00-" + "a" * 32 + "-" + "b" * 15 + "-01",  # span_id corto
        "00-" + "g" * 32 + "-" + "b" * 16 + "-01",  # trace_id no-hex
        "00-" + "a" * 32 + "-" + "z" * 16 + "-01",  # span_id no-hex
        "00-" + "A" * 32 + "-" + "b" * 16 + "-01",  # mayúsculas: W3C exige minúsculas
        "00-" + "0" * 32 + "-" + "b" * 16 + "-01",  # trace_id todo ceros
        "00-" + "a" * 32 + "-" + "0" * 16 + "-01",  # span_id todo ceros
        "00-" + "a" * 32 + "-" + "b" * 16,  # faltan campos
    ],
)
def test_parse_traceparent_rejects(value):
    assert context.parse_traceparent(value) is None
