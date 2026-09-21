"""Invariantes de infraestructura para observabilidad (Fase 0 en adelante).

nginx (F0), entrypoints de uvicorn y arranque de Celery (F1c).

`/metrics`, cuando exista, no debe ser alcanzable desde el hostname público:
`location /` (más abajo, en el mismo `server`) proxea absolutamente todo al
backend, así que sin un bloque que lo intercepte antes, la app publicaría en
internet el inventario completo de rutas con su tráfico y su latencia — mejor
mapa de la app que el Swagger que ya se apaga en producción.

Se lee el archivo como texto (mismo patrón que `test_compose_prod_invariants.py`):
NO se usa PyYAML porque no está en requirements.txt y CI instala solo eso, y
nginx no es YAML de todos modos. Este archivo lo amplían tareas posteriores
(T4, T6) con más invariantes de observabilidad; se mantiene en helpers chicos,
uno por invariante, para que crezca sin volverse un solo test gigante.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_PROD_CONF = REPO_ROOT / "docker" / "nginx" / "nginx.prod.conf"
ENTRYPOINT_FASTAPI = REPO_ROOT / "docker" / "backend" / "entrypoint-fastapi.sh"
ENTRYPOINTS = (
    ENTRYPOINT_FASTAPI,
    # El de dev lo usan `backend` Y `sockets` en docker-compose.dev.yml.
    REPO_ROOT / "docker" / "backend" / "entrypoint-fastapi-dev.sh",
)
CELERY_APP = REPO_ROOT / "itcj2" / "celery_app.py"
COMPOSE_PROD = REPO_ROOT / "docker" / "compose" / "docker-compose.prod.yml"

# Los tres servicios que sirven HTTP con --workers > 1 o Socket.IO: son los que
# necesitan el tmpfs de mmap para prometheus_client (F2b). Celery no entra:
# corre en un solo proceso por contenedor y el registro plano ya le basta.
PROMETHEUS_TMPFS_SERVICES = ("backend-blue", "backend-green", "sockets")
CELERY_SERVICES = ("celery-worker", "celery-worker-reports", "celery-beat")


def _find_matching_brace(text: str, open_index: int) -> int:
    """Índice del `}` que cierra el `{` en `open_index` (conteo balanceado).

    Necesario porque un bloque nginx (`server { ... location { ... } ... }`)
    anida llaves: el primer `}` después de la apertura casi nunca es el que
    cierra ese bloque.
    """
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError(f"llave sin cerrar a partir del índice {open_index}")


def _extract_block(text: str, header: str, start: int = 0) -> tuple[str, int, int]:
    """Cuerpo (sin llaves) e (inicio, fin) del primer bloque `header ... }`.

    `header` debe incluir la `{` de apertura literal (p. ej. ``"server {"`` o
    ``"location = /metrics {"``). Match por substring literal, NO regex: así
    ``"location = /metrics"`` (match exacto de nginx) nunca se confunde con
    ``"location /metrics"`` (prefijo) ni ``"server_tokens"`` con ``"server {"``.
    Lanza ``ValueError`` si el header no aparece — eso es lo que hace fallar el
    test hoy, antes de que el bloque exista.
    """
    header_index = text.index(header, start)
    open_index = header_index + len(header) - 1  # la '{' es el último char del header
    close_index = _find_matching_brace(text, open_index)
    return text[open_index + 1 : close_index], header_index, close_index


def _server_block(text: str) -> tuple[str, int, int]:
    """El único `server { ... }` que sirve la app (nginx.prod.conf no tiene más)."""
    return _extract_block(text, "server {")


def test_nginx_bloquea_metrics():
    """`/metrics` responde 404 desde nginx, sin llegar nunca al backend.

    Falla hoy porque el archivo no tiene ninguna `location` que mencione
    `/metrics`: `location /` (la última del `server`) proxea todo a
    `upstream backend`, así que en cuanto la app registre `/metrics` quedaría
    publicado en el hostname público sin este bloque.
    """
    full_text = NGINX_PROD_CONF.read_text(encoding="utf-8")
    _, server_start, server_end = _server_block(full_text)

    metrics_body, metrics_start, metrics_end = _extract_block(
        full_text, "location = /metrics {"
    )

    assert server_start < metrics_start and metrics_end < server_end, (
        "el bloque 'location = /metrics' debe estar DENTRO del server que sirve la app"
    )
    assert "return 404" in metrics_body, "el bloque debe cortar en seco con 404"
    assert "proxy_pass" not in metrics_body, (
        "el bloque no debe reenviar al backend (dejaría de estar cerrado)"
    )


def _exec_uvicorn(script: Path) -> str:
    """El comando `exec uvicorn ...` completo, con sus líneas de continuación
    (barra invertida al final) unidas en una sola cadena."""
    lines = script.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith("exec uvicorn")
    )
    parts = []
    for line in lines[start:]:
        stripped = line.rstrip()
        parts.append(stripped.rstrip("\\"))
        if not stripped.endswith("\\"):
            break
    return " ".join(parts)


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_uvicorn_arranca_sin_access_log(script):
    """La línea por petición la emite `ObservabilityMiddleware` (JSON, ruta
    plantillada, duración). Con el access log de uvicorn serían dos líneas por
    petición: el doble de volumen en Loki y doble conteo en cualquier panel."""
    assert "--no-access-log" in _exec_uvicorn(script)


def test_celery_configura_logging_por_la_senal_setup_logging():
    """Una llamada suelta a `configure_logging()` al importar `celery_app.py`
    la borra el worker al arrancar (`worker_hijack_root_logger`, activo por
    defecto): el worker nunca emitiría JSON. Con un receptor conectado a
    `celery.signals.setup_logging`, Celery se salta ese secuestro."""
    text = CELERY_APP.read_text(encoding="utf-8")

    assert re.search(r"\bsetup_logging\.connect\b", text), (
        "celery_app.py debe conectar un receptor a celery.signals.setup_logging"
    )
    # Sentencias de nivel de módulo = líneas sin sangría.
    module_level_calls = re.findall(
        r"^(?![#\s]|def |class |@).*\bconfigure_logging\(", text, re.MULTILINE
    )
    assert module_level_calls == [], (
        "configure_logging() a nivel de módulo la borra el worker al arrancar"
    )


def test_entrypoint_fastapi_prepara_prometheus_multiproc_dir_antes_de_uvicorn():
    """Con `--workers 4` cada worker es un proceso: el registro normal de
    `prometheus_client` daría el número de UNO al azar (mal, no ausente). El
    bloque exporta `PROMETHEUS_MULTIPROC_DIR` (default `/run/prometheus`, el
    tmpfs propio del compose) y limpia + recrea el directorio ANTES de
    `exec uvicorn`.

    El `rm -rf` es obligatorio: si esa ruta alguna vez no fuera un tmpfs, los
    ficheros del arranque anterior se seguirían sumando al total; y dentro de
    la misma vida del contenedor, un worker respawneado suma de más a los
    Gauge livesum porque nadie llama a `multiprocess.mark_process_dead()`.
    """
    stripped = [
        line.strip()
        for line in ENTRYPOINT_FASTAPI.read_text(encoding="utf-8").splitlines()
    ]

    export_idx = next(
        i
        for i, line in enumerate(stripped)
        if line.startswith("export PROMETHEUS_MULTIPROC_DIR=")
    )
    assert "${PROMETHEUS_MULTIPROC_DIR:-/run/prometheus}" in stripped[export_idx], (
        "el default debe ser /run/prometheus (el tmpfs que declara el compose)"
    )

    rm_idx = next(
        i
        for i, line in enumerate(stripped)
        if line.startswith('rm -rf "$PROMETHEUS_MULTIPROC_DIR"')
    )
    mkdir_idx = next(
        i
        for i, line in enumerate(stripped)
        if line.startswith('mkdir -p "$PROMETHEUS_MULTIPROC_DIR"')
    )
    exec_idx = next(
        i for i, line in enumerate(stripped) if line.startswith("exec uvicorn")
    )

    assert export_idx < rm_idx < mkdir_idx < exec_idx, (
        "export, 'rm -rf' y 'mkdir -p' deben ir en ese orden, antes de 'exec uvicorn'"
    )


def _service_lines(text: str, service: str) -> list[str]:
    """Líneas del cuerpo de un servicio del compose (sin su propia cabecera).

    Mismo criterio que `test_compose_prod_invariants.py::_service_env`: el
    nombre del servicio es una clave con indentación de EXACTAMENTE 2 espacios;
    la siguiente clave con esa misma indentación (otro servicio, o `volumes:`
    a nivel de documento cuando trae sub-claves) cierra el bloque.
    """
    lines: list[str] = []
    in_service = False
    for line in text.splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            in_service = line.strip().rstrip(":") == service
            continue
        if in_service:
            lines.append(line)
    return lines


def _service_tmpfs(text: str, service: str) -> list[str]:
    """Entradas del bloque `tmpfs:` de un servicio (lista de strings sueltos,
    a diferencia de `environment:` que es `- CLAVE=valor`)."""
    entries: list[str] = []
    in_tmpfs = False
    for line in _service_lines(text, service):
        stripped = line.strip()
        if stripped == "tmpfs:":
            in_tmpfs = True
            continue
        if not in_tmpfs:
            continue
        if stripped.startswith("- "):
            entries.append(stripped[2:])
        elif stripped and not stripped.startswith("#"):
            in_tmpfs = False  # empezó otra clave del servicio
    return entries


@pytest.mark.parametrize("service", PROMETHEUS_TMPFS_SERVICES)
def test_tmpfs_dedicado_para_prometheus_multiproc(service):
    """`/run/prometheus` debe ser un tmpfs PROPIO, no `/dev/shm`: el compose
    solo declara `shm_size` en `postgres`, así que `/dev/shm` en estos
    servicios son los 64 MB por defecto de Docker, a compartir con lo que sea.
    `mode=1777` para que cualquier worker (mismo UID) pueda escribir sus
    ficheros mmap."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    entries = _service_tmpfs(text, service)
    assert "/run/prometheus:size=64m,mode=1777" in entries, (
        f"{service}: falta 'tmpfs: - /run/prometheus:size=64m,mode=1777' en {COMPOSE_PROD.name}"
    )


def test_celery_no_declara_prometheus_multiproc_dir():
    """El export vive SOLO en el entrypoint HTTP (`entrypoint-fastapi.sh`).
    Cada contenedor de Celery corre un único proceso, así que el registro
    plano de `prometheus_client` (sin `PROMETHEUS_MULTIPROC_DIR`) ya es
    correcto ahí; ponerle la env var de todos modos activaría por accidente
    el modo multiproceso sobre un directorio que nadie prepara ni limpia."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    for service in CELERY_SERVICES:
        block = "\n".join(_service_lines(text, service))
        assert "PROMETHEUS_MULTIPROC_DIR" not in block, (
            f"{service}: no debe declarar PROMETHEUS_MULTIPROC_DIR "
            "(el export vive solo en el entrypoint HTTP)"
        )
