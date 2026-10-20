"""`reap_dead_workers()` y `render_latest()` en modo multiproceso (plan §9.16).

Por qué subprocesos: `prometheus_client` elige la clase de valores (mmap por
proceso o valor en memoria) UNA vez, al importarse `prometheus_client.values`,
según `PROMETHEUS_MULTIPROC_DIR`. El proceso de pytest ya lo importó sin esa
variable, así que los "workers" que escriben, y el que atiende el scrape,
tienen que ser procesos nuevos con la variable puesta desde el arranque —
igual que en producción, donde la exporta el entrypoint antes de uvicorn.

El escenario reproduce lo que hace `uvicorn --workers` al respawnear: un
worker muere a mitad de una petición (su in-flight quedó en 1 en su fichero)
y otro sigue vivo con una petición en curso.
"""
import logging
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.multiprocess import MultiProcessCollector
from prometheus_client.parser import text_string_to_metric_families

from itcj2.observability.metrics import reap_dead_workers

REPO_ROOT = Path(__file__).resolve().parents[3]

# Un "worker": deja una petición en vuelo, una contada y una medida, y
# anuncia su PID. Con "exit" lo imprime y termina; con "stay" lo escribe en el
# fichero `argv[2]` (atómico: tmp + replace) y se queda vivo hasta que se le
# cierre stdin. Por fichero y no por stdout: el test lo espera con plazo, sin
# un `readline()` que se colgaría para siempre si el hijo se atasca.
_WORKER = textwrap.dedent("""
    import os, sys
    from itcj2.observability import metrics
    metrics.HTTP_IN_FLIGHT.labels(app="helpdesk").inc()
    metrics.HTTP_REQUESTS.labels(
        app="helpdesk", method="GET", route="/x/{id}", status="200"
    ).inc()
    metrics.HTTP_REQUEST_DURATION.labels(
        app="helpdesk", method="GET", route="/x/{id}"
    ).observe(0.1)
    if sys.argv[1] == "stay":
        ready = sys.argv[2]
        with open(ready + ".tmp", "w") as f:
            f.write(str(os.getpid()))
        os.replace(ready + ".tmp", ready)
        sys.stdin.read()
    else:
        print(os.getpid(), flush=True)
""")

# El worker que atiende el scrape: exactamente lo que hace GET /metrics.
_SCRAPER = textwrap.dedent("""
    import sys
    from itcj2.observability.metrics import render_latest
    body, _ = render_latest()
    sys.stdout.write(body.decode())
""")


def _env(multiproc_dir: Path) -> dict:
    env = dict(os.environ)
    env["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p
    )
    return env


def _run(code: str, env: dict, *args: str) -> str:
    """Corre `code` en un proceso nuevo; si falla, el stderr va al mensaje."""
    proc = subprocess.run(
        [sys.executable, "-c", code, *args],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _samples(body: str) -> dict:
    """`{(nombre, etiquetas ordenadas): valor}` de una exposición de texto."""
    return {
        (s.name, tuple(sorted(s.labels.items()))): s.value
        for family in text_string_to_metric_families(body)
        for s in family.samples
    }


def _read_without_reaping(multiproc_dir: Path) -> dict:
    # Leer los ficheros no depende de la clase de valores: se puede hacer
    # desde el proceso de pytest. Es la vista SIN reaper.
    registry = CollectorRegistry()
    MultiProcessCollector(registry, path=str(multiproc_dir))
    return _samples(generate_latest(registry).decode())


IN_FLIGHT = ("itcj_http_requests_in_flight", (("app", "helpdesk"),))
REQUESTS = (
    "itcj_http_requests_total",
    (("app", "helpdesk"), ("method", "GET"), ("route", "/x/{id}"), ("status", "200")),
)
DURATION_COUNT = (
    "itcj_http_request_duration_seconds_count",
    (("app", "helpdesk"), ("method", "GET"), ("route", "/x/{id}")),
)


def _wait_for_ready(proc: subprocess.Popen, ready: Path, timeout: float = 60) -> int:
    """PID que el worker vivo dejó en `ready`, con plazo: si el hijo muere
    antes o se atasca, el test falla con su stderr en vez de colgarse."""
    deadline = time.monotonic() + timeout
    while not ready.exists():
        if proc.poll() is not None:
            raise AssertionError(
                f"el worker murió (rc={proc.returncode}) sin avisar: {proc.stderr.read()}"
            )
        if time.monotonic() > deadline:
            raise AssertionError(f"el worker no avisó en {timeout} s")
        time.sleep(0.02)
    return int(ready.read_text())


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    multiproc_dir = tmp_path_factory.mktemp("prometheus_multiproc")
    # Fuera del dir de mmap: el test compara los ficheros de ese dir.
    ready = tmp_path_factory.mktemp("worker_ready") / "live.pid"
    env = _env(multiproc_dir)

    dead_pid = int(_run(_WORKER, env, "exit").strip())

    # `with`: al salir cierra los pipes (sin ResourceWarning) y recoge al hijo.
    with subprocess.Popen(
        [sys.executable, "-c", _WORKER, "stay", str(ready)],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    ) as live:
        try:
            live_pid = _wait_for_ready(live, ready)
            files_before = set(os.listdir(multiproc_dir))
            before = _read_without_reaping(multiproc_dir)

            scraped = _run(_SCRAPER, env)

            yield {
                "multiproc_dir": multiproc_dir,
                "dead_pid": dead_pid,
                "live_pid": live_pid,
                "files_before": files_before,
                "files_after": set(os.listdir(multiproc_dir)),
                "before": before,
                "after": _samples(scraped),
            }
        finally:
            live.stdin.close()
            try:
                live.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # Un hijo atascado no puede sobrevivir a la sesión de pytest.
                live.kill()
                live.wait()


def test_dead_worker_livesum_gauge_stops_being_summed(scenario):
    # Sin reaper, el residuo del muerto se suma para siempre (§9.16): 2.
    assert scenario["before"][IN_FLIGHT] == 2
    # Tras el reaper solo cuenta la petición del vivo.
    assert scenario["after"][IN_FLIGHT] == 1
    dead_gauge = f"gauge_livesum_{scenario['dead_pid']}.db"
    assert dead_gauge in scenario["files_before"]
    assert dead_gauge not in scenario["files_after"]


def test_dead_worker_counter_and_histogram_files_are_kept(scenario):
    dead_pid = scenario["dead_pid"]
    for name in (f"counter_{dead_pid}.db", f"histogram_{dead_pid}.db"):
        assert name in scenario["files_after"], name
    # Las peticiones que sirvió el muerto siguen contando.
    assert scenario["after"][REQUESTS] == 2
    assert scenario["after"][DURATION_COUNT] == 2


def test_live_worker_files_are_untouched(scenario):
    live_pid = scenario["live_pid"]
    live_files = {f for f in scenario["files_before"] if f.endswith(f"_{live_pid}.db")}
    assert f"gauge_livesum_{live_pid}.db" in live_files
    assert live_files <= scenario["files_after"]


# ---------------------------------------------------------------------------
# Uso del directorio de mmap (R25): lleno = SIGBUS, hay que verlo venir
# ---------------------------------------------------------------------------
DIR_USED = ("itcj_metrics_dir_used_bytes", ())
DIR_SIZE = ("itcj_metrics_dir_size_bytes", ())


def test_scrape_reports_the_multiproc_dir_usage(scenario):
    # El scrape del subproceso (modo multiproceso real) lee `statvfs` del
    # directorio de `PROMETHEUS_MULTIPROC_DIR`, no de otro sistema de
    # ficheros: el tamaño cuadra exacto con el que ve pytest.
    stats = os.statvfs(scenario["multiproc_dir"])
    after = scenario["after"]

    assert after[DIR_SIZE] == stats.f_blocks * stats.f_frsize
    assert 0 < after[DIR_USED] <= after[DIR_SIZE]


def test_flat_registry_does_not_report_the_dir_usage(monkeypatch):
    # Sin la variable (tests, dev) no hay directorio que medir.
    from itcj2.observability.metrics import render_latest

    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    body = render_latest()[0].decode()

    assert "itcj_metrics_dir_used_bytes" not in body
    assert "itcj_metrics_dir_size_bytes" not in body


def test_dir_usage_never_raises_on_a_missing_dir(tmp_path, monkeypatch, caplog):
    # Un fallo aquí no puede tirar el scrape entero: se omite la familia.
    from itcj2.observability import metrics

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path / "no-existe"))
    collectors = [
        c for c in metrics._scrape_collectors
        if isinstance(c, metrics.MetricsDirCollector)
    ]
    assert len(collectors) == 1, "el colector del dir debe estar registrado una vez"

    with caplog.at_level(logging.WARNING, logger="itcj2.observability"):
        families = list(collectors[0].collect())

    assert families == []
    assert any("no-existe" in r.getMessage() for r in caplog.records)


def test_reaper_never_raises_on_a_missing_dir(tmp_path):
    assert reap_dead_workers(str(tmp_path / "no-existe")) == []


def test_reaper_ignores_files_that_are_not_live_gauges(tmp_path):
    # PID que no existe (por encima del pid_max de Linux): si el reaper
    # tocara algo que no es `gauge_live*_<pid>.db`, se notaría aquí.
    ghost = 2**22 + 7
    kept = [
        f"counter_{ghost}.db",
        f"histogram_{ghost}.db",
        f"gauge_all_{ghost}.db",
        "gauge_livesum_nopid.db",
        "notas.txt",
    ]
    for name in kept + [f"gauge_livesum_{ghost}.db"]:
        (tmp_path / name).write_bytes(b"")

    assert reap_dead_workers(str(tmp_path)) == [ghost]
    assert sorted(os.listdir(tmp_path)) == sorted(kept)
