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
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.multiprocess import MultiProcessCollector
from prometheus_client.parser import text_string_to_metric_families

from itcj2.observability.metrics import reap_dead_workers

REPO_ROOT = Path(__file__).resolve().parents[3]

# Un "worker": deja una petición en vuelo, una contada y una medida, y
# anuncia su PID. Con "stay" se queda vivo hasta que se le cierre stdin.
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
    print(os.getpid(), flush=True)
    if sys.argv[1] == "stay":
        sys.stdin.read()
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


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    multiproc_dir = tmp_path_factory.mktemp("prometheus_multiproc")
    env = _env(multiproc_dir)

    dead_pid = int(_run(_WORKER, env, "exit").strip())

    live = subprocess.Popen(
        [sys.executable, "-c", _WORKER, "stay"],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        live_pid = int(live.stdout.readline().strip())
        files_before = set(os.listdir(multiproc_dir))
        before = _read_without_reaping(multiproc_dir)

        scraped = _run(_SCRAPER, env)

        yield {
            "dead_pid": dead_pid,
            "live_pid": live_pid,
            "files_before": files_before,
            "files_after": set(os.listdir(multiproc_dir)),
            "before": before,
            "after": _samples(scraped),
        }
    finally:
        live.stdin.close()
        live.wait(timeout=30)


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
