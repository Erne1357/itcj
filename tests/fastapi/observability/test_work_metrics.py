"""Medidor de trabajo pesado y de llamadas salientes (plan Fase 4, Task 1).

`measured()` / `measured_outbound()` envuelven código de NEGOCIO (LibreOffice,
los Excel/CSV, MS Graph, la API de fútbol): lo que se prueba aquí, antes que
el número, es que nunca cambian lo que pasa dentro — la MISMA excepción
(identidad, no solo el tipo), el MISMO valor — y que un fallo de la medición
se traga.

Los histogramas son de MÓDULO y acumulan entre tests: todo se mide como DELTA
con `REGISTRY.get_sample_value`, que exige el juego de etiquetas EXACTO (una
etiqueta de más o de menos daría `None` y el delta no cuadraría: eso ya fija
el contrato de etiquetas).
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import requests
from prometheus_client import REGISTRY

from itcj2.config import get_settings
from itcj2.observability import metrics, work

REPO_ROOT = Path(__file__).resolve().parents[3]

RENDER = "itcj_document_render_seconds"
OUTBOUND = "itcj_outbound_request_seconds"
OUTCOMES = ("ok", "error", "timeout")

RENDER_LABELS = {"kind": "orden_trabajo", "engine": "libreoffice"}
OUTBOUND_LABELS = {"target": "msgraph"}


def _counts(name: str, labels: dict) -> dict:
    return {
        outcome: REGISTRY.get_sample_value(
            f"{name}_count", {**labels, "outcome": outcome}
        ) or 0.0
        for outcome in OUTCOMES
    }


def _delta(before: dict, after: dict) -> dict:
    return {outcome: after[outcome] - before[outcome] for outcome in OUTCOMES}


def _only(outcome: str, times: float = 1.0) -> dict:
    return {o: (times if o == outcome else 0.0) for o in OUTCOMES}


def _family_count(name: str) -> float:
    """Observaciones de TODAS las series de un histograma, sea cual sea su
    etiqueta: lo que no se registró bajo ningún juego de etiquetas."""
    total = 0.0
    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name == f"{name}_count":
                total += sample.value
    return total


@pytest.fixture
def fresh_failure_log(monkeypatch):
    """El aviso de fallo de escritura va con límite de frecuencia GLOBAL: sin
    reiniciarlo, un test anterior que ya avisó dejaría mudo a este."""
    monkeypatch.setattr(work, "_last_failure_log", float("-inf"))


# ---------------------------------------------------------------------------
# Contrato (global-constraints, "Contratos NUEVOS de la ronda 2")
# ---------------------------------------------------------------------------

def test_document_render_histogram_matches_the_contract():
    histogram = metrics.DOCUMENT_RENDER_DURATION
    assert histogram._name == RENDER
    assert histogram._labelnames == ("kind", "engine", "outcome")
    # R31: primer bucket en 50 ms, no en 0,5 s (el oficio y los CSV son
    # sub-segundo); tope en 60 s, el `timeout=60` de LibreOffice.
    assert histogram._upper_bounds == [
        0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0, float("inf"),
    ]


def test_outbound_histogram_matches_the_contract():
    histogram = metrics.OUTBOUND_REQUEST_DURATION
    assert histogram._name == OUTBOUND
    assert histogram._labelnames == ("target", "outcome")
    assert histogram._upper_bounds == [
        0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0, float("inf"),
    ]


def test_closed_label_sets_match_the_contract():
    assert work.DOCUMENT_KINDS == frozenset({
        "solicitud", "orden_trabajo", "inventory_export",
        "inventory_report_equipment", "inventory_report_movements",
        "inventory_report_warranty", "inventory_report_maintenance",
        "inventory_report_lifecycle", "retirement_oficio", "agendatec_report",
    })
    assert work.DOCUMENT_ENGINES == frozenset(
        {"libreoffice", "openpyxl", "xlsxwriter", "csv"}
    )
    assert work.OUTBOUND_TARGETS == frozenset({"msgraph", "football_api"})
    assert work.OUTCOMES == frozenset(OUTCOMES)


# ---------------------------------------------------------------------------
# measured(kind, engine)
# ---------------------------------------------------------------------------

def test_measured_records_one_ok_observation_timing_the_block():
    before = _counts(RENDER, RENDER_LABELS)
    sum_labels = {**RENDER_LABELS, "outcome": "ok"}
    sum_before = REGISTRY.get_sample_value(f"{RENDER}_sum", sum_labels) or 0.0

    with work.measured(**RENDER_LABELS):
        time.sleep(0.05)  # lo que tardaría `subprocess.run` de LibreOffice

    assert _delta(before, _counts(RENDER, RENDER_LABELS)) == _only("ok")
    sum_after = REGISTRY.get_sample_value(f"{RENDER}_sum", sum_labels)
    assert sum_after - sum_before >= 0.05


TIMEOUTS = [
    pytest.param(lambda: subprocess.TimeoutExpired(["soffice"], 60), id="subprocess"),
    pytest.param(lambda: requests.Timeout("lento"), id="requests"),
    # También es `ConnectionError`: gana timeout, es el timeout del cliente.
    pytest.param(lambda: requests.ConnectTimeout("lento"), id="requests-connect"),
    pytest.param(lambda: httpx.ReadTimeout("lento"), id="httpx"),
    pytest.param(lambda: TimeoutError("lento"), id="builtin"),
]

ERRORS = [
    pytest.param(lambda: RuntimeError("Error al convertir a PDF"), id="runtime"),
    pytest.param(lambda: requests.ConnectionError("sin red"), id="requests-conn"),
    pytest.param(lambda: httpx.ConnectError("sin red"), id="httpx-conn"),
    pytest.param(lambda: subprocess.CalledProcessError(1, ["soffice"]), id="called"),
    # Lo que no es `Exception` también sale igual (y cuenta como error).
    pytest.param(lambda: KeyboardInterrupt(), id="base-exception"),
]


@pytest.mark.parametrize("make_exc", TIMEOUTS)
def test_measured_timeout_records_timeout_and_reraises_the_same_exception(make_exc):
    exc = make_exc()
    before = _counts(RENDER, RENDER_LABELS)

    with pytest.raises(type(exc)) as info:
        with work.measured(**RENDER_LABELS):
            raise exc

    assert info.value is exc
    assert _delta(before, _counts(RENDER, RENDER_LABELS)) == _only("timeout")


@pytest.mark.parametrize("make_exc", ERRORS)
def test_measured_other_exception_records_error_and_reraises_it(make_exc):
    exc = make_exc()
    before = _counts(RENDER, RENDER_LABELS)

    with pytest.raises(type(exc)) as info:
        with work.measured(**RENDER_LABELS):
            raise exc

    assert info.value is exc
    assert _delta(before, _counts(RENDER, RENDER_LABELS)) == _only("error")


def test_a_generator_measured_while_streaming():
    """Un export que se genera perezosamente (se consume al hacer streaming)
    mide dentro del generador: consumido entero es `ok`; cerrado a medias
    (el cliente se fue) es `error`, y el cierre sigue limpio — sin
    `RuntimeError: generator ignored GeneratorExit`."""
    labels = {"kind": "inventory_report_equipment", "engine": "csv"}

    def rows():
        with work.measured(**labels):
            yield "cabecera"
            yield "fila"

    before = _counts(RENDER, labels)
    assert list(rows()) == ["cabecera", "fila"]
    assert _delta(before, _counts(RENDER, labels)) == _only("ok")

    before = _counts(RENDER, labels)
    stream = rows()
    assert next(stream) == "cabecera"
    stream.close()
    assert _delta(before, _counts(RENDER, labels)) == _only("error")


def test_mark_error_records_error_without_an_exception():
    before = _counts(RENDER, RENDER_LABELS)

    with work.measured(**RENDER_LABELS) as measurement:
        measurement.mark_error()

    assert _delta(before, _counts(RENDER, RENDER_LABELS)) == _only("error")


def test_measured_as_decorator_keeps_arguments_and_return_value():
    sentinel = object()
    labels = {"kind": "inventory_export", "engine": "openpyxl"}
    before = _counts(RENDER, labels)

    @work.measured(**labels)
    def export(a, *, b):
        return sentinel, a, b

    first = export(1, b=2)
    export(3, b=4)

    assert first[0] is sentinel and first[1:] == (1, 2)
    # Un cronómetro nuevo por llamada: dos llamadas, dos observaciones.
    assert _delta(before, _counts(RENDER, labels)) == _only("ok", times=2)


def test_measured_as_decorator_reraises_the_same_exception():
    exc = RuntimeError("plantilla corrupta")
    labels = {"kind": "retirement_oficio", "engine": "openpyxl"}
    before = _counts(RENDER, labels)

    @work.measured(**labels)
    def render():
        raise exc

    with pytest.raises(RuntimeError) as info:
        render()

    assert info.value is exc
    assert _delta(before, _counts(RENDER, labels)) == _only("error")


# ---------------------------------------------------------------------------
# La medición que falla nunca rompe el trabajo (regla de oro 2, R27)
# ---------------------------------------------------------------------------

def test_a_failing_metric_write_is_swallowed_and_logged(caplog, fresh_failure_log):
    failing = RuntimeError("mmap no se pudo crecer")
    with patch.object(
        metrics.DOCUMENT_RENDER_DURATION, "labels", side_effect=failing
    ):
        with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
            with work.measured(**RENDER_LABELS):
                result = "pdf"
            with work.measured(**RENDER_LABELS):
                pass

    assert result == "pdf"
    logged = [r for r in caplog.records if r.exc_info and r.exc_info[1] is failing]
    # Dos fallos seguidos, UN aviso: si el directorio se rompe falla cada
    # render, y un traceback por render inundaría Loki.
    assert len(logged) == 1


def test_a_failing_metric_write_never_replaces_the_business_exception(fresh_failure_log):
    business = ValueError("ticket sin folio")
    with patch.object(
        metrics.DOCUMENT_RENDER_DURATION, "labels",
        side_effect=RuntimeError("mmap no se pudo crecer"),
    ):
        with pytest.raises(ValueError) as info:
            with work.measured(**RENDER_LABELS):
                raise business

    assert info.value is business


def test_metrics_import_failure_is_logged_once_and_the_work_still_runs(
    monkeypatch, caplog
):
    # El import que falla no se reintenta: una segunda vuelta registraría
    # otra vez las métricas que alcanzaron a declararse y fallaría por
    # "Duplicated timeseries" en cada medición.
    monkeypatch.setattr(work, "_metrics", None)
    monkeypatch.setattr(work, "_metrics_unavailable", False)
    monkeypatch.setitem(sys.modules, "itcj2.observability.metrics", None)

    ran = 0
    with caplog.at_level(logging.ERROR, logger="itcj2.observability"):
        for _ in range(3):
            with work.measured(**RENDER_LABELS):
                ran += 1
        with work.measured_outbound(**OUTBOUND_LABELS) as measurement:
            measurement.mark_status(202)
            ran += 1

    assert ran == 4
    logged = [
        r for r in caplog.records
        if r.exc_info and isinstance(r.exc_info[1], ImportError)
    ]
    assert len(logged) == 1


def test_measured_survives_the_multiproc_dir_celery_could_inherit(tmp_path):
    """El escenario real de Celery (regla de oro 1): con
    `PROMETHEUS_MULTIPROC_DIR` heredada del `.env` hacia un directorio que
    nadie crea, importar `metrics` revienta (los gauges sin etiquetas abren
    su mmap al declararse). `measured()` corre en ese mismo proceso cuando la
    tarea `convert_document` genera un PDF: el PDF tiene que salir igual."""
    code = (
        "from itcj2.observability import work\n"
        "with work.measured('solicitud', 'libreoffice'):\n"
        "    result = 'pdf'\n"
        "with work.measured_outbound('msgraph') as m:\n"
        "    m.mark_status(202)\n"
        "print('RESULT=%s' % result)\n"
    )
    env = dict(os.environ)
    env["PROMETHEUS_MULTIPROC_DIR"] = str(tmp_path / "nadie-lo-crea")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p
    )

    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )

    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "RESULT=pdf" in proc.stdout
    # Anti-vacuidad: el import de `metrics` SÍ falló por el mmap (si no, esto
    # no probaría la guarda)...
    assert "FileNotFoundError" in proc.stderr, proc.stderr[-3000:]
    # ...y se avisó UNA vez para las dos mediciones, sin reintentar el import
    # (el reintento fallaría distinto, por "Duplicated timeseries").
    assert proc.stderr.count("no se pudo importar") == 1, proc.stderr[-3000:]
    assert "Duplicated timeseries" not in proc.stderr, proc.stderr[-3000:]


# ---------------------------------------------------------------------------
# Conjunto cerrado de etiquetas: ruidoso en desarrollo, tolerante en prod
# ---------------------------------------------------------------------------

def test_strict_labels_is_on_under_pytest(monkeypatch):
    # CI no define FLASK_ENV (gana el default "production" de config.py):
    # sin esta señal, la suite de CI correría en modo tolerante y una
    # etiqueta mal escrita pasaría en verde. FLASK_ENV fijado a "production"
    # como en CI: con el "development" del `.env` de dev esto pasaría aunque
    # la señal de pytest no existiera.
    monkeypatch.setattr(get_settings(), "FLASK_ENV", "production")
    assert "PYTEST_CURRENT_TEST" in os.environ
    assert work.strict_labels() is True


def test_strict_labels_outside_pytest_follows_flask_env(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(get_settings(), "FLASK_ENV", "production")
    assert work.strict_labels() is False

    monkeypatch.setattr(get_settings(), "FLASK_ENV", "development")
    assert work.strict_labels() is True


def test_closed_label_ok_accepts_members_of_the_set():
    assert work.closed_label_ok(RENDER, "kind", "solicitud", work.DOCUMENT_KINDS)


def test_closed_label_ok_raises_in_strict_mode():
    with pytest.raises(ValueError, match="conjunto cerrado"):
        work.closed_label_ok(RENDER, "kind", "factura", work.DOCUMENT_KINDS)


def test_closed_label_ok_warns_once_per_label_in_production(monkeypatch, caplog):
    monkeypatch.setattr(work, "strict_labels", lambda: False)
    monkeypatch.setattr(work, "_warned_labels", set())

    with caplog.at_level(logging.WARNING, logger="itcj2.observability"):
        results = [
            work.closed_label_ok(RENDER, "kind", value, work.DOCUMENT_KINDS)
            for value in ("factura", "factura", "recibo")
        ]
        # Un valor no hasheable tampoco revienta: es otro "fuera del conjunto".
        results.append(work.closed_label_ok(OUTBOUND, "target", ["x"], work.OUTBOUND_TARGETS))

    assert results == [False, False, False, False]
    warnings = [
        r for r in caplog.records
        if r.name == "itcj2.observability" and r.levelno == logging.WARNING
    ]
    # Una vez por (métrica, etiqueta), no por valor: un valor que venga de la
    # entrada abriría un set sin tope y un aviso por petición.
    assert [(RENDER in r.getMessage(), OUTBOUND in r.getMessage()) for r in warnings] == [
        (True, False), (False, True),
    ]
    assert "factura" in warnings[0].getMessage()


@pytest.mark.parametrize(
    "open_cm",
    [
        pytest.param(lambda: work.measured("factura", "libreoffice"), id="kind"),
        pytest.param(lambda: work.measured("solicitud", "pandoc"), id="engine"),
        pytest.param(lambda: work.measured_outbound("github"), id="target"),
    ],
)
def test_label_outside_the_closed_set_fails_before_the_block_in_development(open_cm):
    ran = []

    with pytest.raises(ValueError, match="conjunto cerrado"):
        with open_cm():
            ran.append(True)

    assert ran == []


def test_label_outside_the_closed_set_in_production_records_nothing(monkeypatch):
    monkeypatch.setattr(work, "strict_labels", lambda: False)
    monkeypatch.setattr(work, "_warned_labels", set())
    render_before = _family_count(RENDER)
    outbound_before = _family_count(OUTBOUND)
    business = RuntimeError("negocio")

    with work.measured("factura", "libreoffice"):
        result = "pdf"
    with pytest.raises(RuntimeError) as info:
        with work.measured_outbound("github"):
            raise business

    assert result == "pdf"
    assert info.value is business
    assert _family_count(RENDER) == render_before
    assert _family_count(OUTBOUND) == outbound_before


# ---------------------------------------------------------------------------
# measured_outbound(target)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status, outcome",
    [(200, "ok"), (202, "ok"), (399, "ok"), (400, "error"), (404, "error"), (503, "error")],
)
def test_measured_outbound_classifies_the_http_status(status, outcome):
    before = _counts(OUTBOUND, OUTBOUND_LABELS)

    with work.measured_outbound(**OUTBOUND_LABELS) as measurement:
        measurement.mark_status(status)

    assert _delta(before, _counts(OUTBOUND, OUTBOUND_LABELS)) == _only(outcome)


def test_measured_outbound_without_status_is_ok():
    labels = {"target": "football_api"}
    before = _counts(OUTBOUND, labels)

    with work.measured_outbound(**labels):
        pass

    assert _delta(before, _counts(OUTBOUND, labels)) == _only("ok")


def test_mark_status_never_raises_on_a_status_it_cannot_read():
    before = _counts(OUTBOUND, OUTBOUND_LABELS)

    with work.measured_outbound(**OUTBOUND_LABELS) as measurement:
        measurement.mark_status(None)
        measurement.mark_status("no-es-un-status")

    assert _delta(before, _counts(OUTBOUND, OUTBOUND_LABELS)) == _only("ok")


@pytest.mark.parametrize("make_exc", TIMEOUTS)
def test_measured_outbound_timeout_records_timeout_and_reraises(make_exc):
    exc = make_exc()
    before = _counts(OUTBOUND, OUTBOUND_LABELS)

    with pytest.raises(type(exc)) as info:
        with work.measured_outbound(**OUTBOUND_LABELS):
            raise exc

    assert info.value is exc
    assert _delta(before, _counts(OUTBOUND, OUTBOUND_LABELS)) == _only("timeout")


@pytest.mark.parametrize("make_exc", ERRORS)
def test_measured_outbound_other_exception_records_error_and_reraises(make_exc):
    exc = make_exc()
    before = _counts(OUTBOUND, OUTBOUND_LABELS)

    with pytest.raises(type(exc)) as info:
        with work.measured_outbound(**OUTBOUND_LABELS):
            raise exc

    assert info.value is exc
    assert _delta(before, _counts(OUTBOUND, OUTBOUND_LABELS)) == _only("error")


def test_a_failing_outbound_metric_write_is_swallowed(fresh_failure_log):
    with patch.object(
        metrics.OUTBOUND_REQUEST_DURATION, "labels",
        side_effect=RuntimeError("mmap no se pudo crecer"),
    ):
        with work.measured_outbound(**OUTBOUND_LABELS) as measurement:
            measurement.mark_status(202)
            response = "enviado"

    assert response == "enviado"
