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

Excepción: el bloque de `PROMETHEUS_MULTIPROC_DIR` del entrypoint se EJECUTA
con bash (ver su sección): un invariante de texto sobre un script de shell
congeló una vez justo la línea que tumbaba producción.
"""
import os
import re
import shutil
import subprocess
import sys
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


def test_celery_arranca_aunque_herede_prometheus_multiproc_dir(tmp_path):
    """Celery no puede depender de que nadie le pase `PROMETHEUS_MULTIPROC_DIR`.

    Todos los servicios leen el mismo `.env` (`env_file`): si la variable
    llegara ahí, Celery pasaría a modo multiproceso contra un directorio que
    nadie crea, y la primera métrica declarada a nivel de módulo (los gauges
    sin etiquetas abren su fichero mmap al declararse) lo mataría AL
    IMPORTAR. Celery solo necesita el logging, así que su cadena de imports
    no debe tocar `prometheus_client` en absoluto. Se importa lo mismo que el
    worker: `itcj2.celery_app` y cada módulo de `include`.
    """
    code = (
        "import sys\n"
        "import itcj2.celery_app as c\n"
        "for name in c.celery_app.conf.include:\n"
        "    __import__(name)\n"
        "print('PROMETHEUS_LOADED=%s' % ('prometheus_client' in sys.modules))\n"
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
    assert "PROMETHEUS_LOADED=False" in proc.stdout, (
        "la cadena de imports de Celery carga prometheus_client: "
        "logging_config no debe importar middleware/metrics"
    )


# ---------------------------------------------------------------------------
# Bloque de PROMETHEUS_MULTIPROC_DIR del entrypoint (F2b, R23)
# ---------------------------------------------------------------------------
# Estos tests EJECUTAN el bloque real con bash, no leen su texto: la versión
# anterior exigía la línea literal `rm -rf "$PROMETHEUS_MULTIPROC_DIR"` y con
# eso congeló un defecto que tumbaba producción. En prod esa ruta es el PUNTO
# DE MONTAJE del tmpfs del compose, y `rmdir` sobre un punto de montaje da
# EBUSY incluso a root: `rm` sale con 1 y, bajo `set -euo pipefail`, el
# contenedor muere antes de `exec uvicorn` (ni blue, ni green, ni sockets).
# Un tmp_path no es un punto de montaje, así que lo que se comprueba es la
# propiedad que sí importa ahí: el directorio se VACÍA en sitio (mismo
# inodo, nunca desenlazado), no se borra y se recrea.

_MULTIPROC_EXPORT = "export PROMETHEUS_MULTIPROC_DIR="

# Comandos del bloque que tocan el disco: los tests de la guarda los
# sustituyen por funciones de bash que solo apuntan la llamada.
_FS_COMMANDS = ("mkdir", "find", "rm", "rmdir")


def _multiproc_block() -> str:
    """Las líneas del entrypoint desde el `export PROMETHEUS_MULTIPROC_DIR=`
    hasta justo antes de `exec uvicorn` (el bloque tal cual se ejecuta)."""
    lines = ENTRYPOINT_FASTAPI.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith(_MULTIPROC_EXPORT)
    )
    end = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith("exec uvicorn")
    )
    assert start < end, "el bloque debe ir ANTES de 'exec uvicorn'"
    return "\n".join(lines[start:end])


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - el contenedor y el runner de CI lo traen
        pytest.skip("bash no disponible para ejecutar el bloque del entrypoint")
    return bash


def _run_block(script: str, multiproc_dir: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir
    return subprocess.run(
        [_bash(), "-euo", "pipefail", "-c", script],
        env=env, cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def test_entrypoint_exporta_el_default_del_tmpfs_del_compose():
    """El default debe ser `/run/prometheus`, la ruta del tmpfs que declara el
    compose de prod (`test_tmpfs_dedicado_para_prometheus_multiproc`)."""
    export_line = next(
        line.strip()
        for line in ENTRYPOINT_FASTAPI.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(_MULTIPROC_EXPORT)
    )
    assert "${PROMETHEUS_MULTIPROC_DIR:-/run/prometheus}" in export_line


def test_entrypoint_vacia_el_dir_de_mmap_en_sitio_sin_borrarlo(tmp_path):
    """Exit 0, directorio vacío y el MISMO directorio (inodo) que antes.

    Se sostiene un descriptor abierto sobre el directorio durante la
    ejecución: si el bloque lo borrara y recreara, el inodo viejo no se
    puede reciclar mientras el descriptor viva (el `st_ino` nuevo difiere) y
    su `st_nlink` cae a 0. Sin el descriptor, un sistema de ficheros que
    recicla inodos al instante podría dar el mismo número y un falso verde.
    """
    multiproc_dir = tmp_path / "prometheus"
    (multiproc_dir / "sub").mkdir(parents=True)
    for name in ("gauge_livesum_101.db", "counter_101.db", "histogram_101.db"):
        (multiproc_dir / name).write_bytes(b"residuo del arranque anterior")
    (multiproc_dir / "sub" / "anidado.db").write_bytes(b"x")

    fd = os.open(multiproc_dir, os.O_RDONLY)
    try:
        inode_before = os.fstat(fd).st_ino

        proc = _run_block(_multiproc_block(), str(multiproc_dir), tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert os.fstat(fd).st_nlink > 0, (
            "el bloque BORRÓ el directorio: sobre el punto de montaje del tmpfs "
            "de prod eso es EBUSY y el contenedor no arranca"
        )
        assert multiproc_dir.stat().st_ino == inode_before, (
            "el directorio se recreó en vez de vaciarse en sitio"
        )
        assert list(multiproc_dir.iterdir()) == []
    finally:
        os.close(fd)


def test_entrypoint_crea_el_dir_si_no_existe(tmp_path):
    """Fuera de prod (sin tmpfs montado) la ruta puede no existir aún."""
    multiproc_dir = tmp_path / "no-existe" / "prometheus"

    proc = _run_block(_multiproc_block(), str(multiproc_dir), tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert multiproc_dir.is_dir()


def test_entrypoint_nunca_borra_el_dir_mismo():
    """Ninguna línea puede quitar el directorio (solo su contenido): `rm`
    o `rmdir` sobre `$PROMETHEUS_MULTIPROC_DIR` sin `/` detrás."""
    var_ref = re.compile(r'\$\{?PROMETHEUS_MULTIPROC_DIR(?::[^}]*)?\}?"?(.?)')
    offenders = []
    for line in _multiproc_block().splitlines():
        code = line.split("#", 1)[0]
        if not re.search(r"(^|[;&|\s])(rm|rmdir)\s", code):
            continue
        for match in var_ref.finditer(code):
            if match.group(1) != "/":
                offenders.append(line.strip())
    assert offenders == [], (
        f"{offenders}: borra el directorio, no su contenido. En prod es el punto "
        "de montaje del tmpfs (EBUSY -> exit 1 bajo set -e). Vaciar con "
        "'find \"$PROMETHEUS_MULTIPROC_DIR\" -mindepth 1 -delete'."
    )


def _shimmed(script: str, log: Path) -> str:
    """`script` con mkdir/find/rm/rmdir sustituidos por funciones que solo
    apuntan su llamada en `log`: el test de la guarda no puede tocar el disco
    aunque la guarda estuviera rota."""
    shims = "\n".join(
        f'{name}() {{ echo "{name} $*" >> "{log}"; }}' for name in _FS_COMMANDS
    )
    return f"{shims}\n{script}"


def _assert_fs_commands_are_bare(script: str) -> None:
    # Las funciones solo tapan comandos llamados por su nombre: una ruta
    # absoluta (/usr/bin/find) se saltaría el shim.
    for name in _FS_COMMANDS:
        assert not re.search(rf"/{name}\b", script), (
            f"el bloque llama a {name} por ruta absoluta: el test de la guarda "
            "ya no es seguro de ejecutar"
        )


def test_shims_de_la_guarda_interceptan_de_verdad(tmp_path):
    """Control positivo: con una ruta válida los shims SÍ reciben mkdir y
    find. Sin esto, el test de abajo podría pasar porque los shims no se
    usan (y entonces la guarda no se estaría probando)."""
    script = _multiproc_block()
    _assert_fs_commands_are_bare(script)
    log = tmp_path / "calls.log"
    target = str(tmp_path / "prometheus")

    proc = _run_block(_shimmed(script, log), target, tmp_path)

    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(c.startswith("mkdir ") and target in c for c in calls), calls
    assert any(c.startswith("find ") and target in c for c in calls), calls


@pytest.mark.parametrize("dangerous", ["/", "//", "/tmp/..", "/tmp/../"])
def test_entrypoint_se_niega_a_vaciar_la_raiz(tmp_path, dangerous):
    """`find / -mindepth 1 -delete` vaciaría el contenedor entero: la guarda
    tiene que abortar ANTES de tocar nada."""
    script = _multiproc_block()
    _assert_fs_commands_are_bare(script)
    log = tmp_path / "calls.log"

    proc = _run_block(_shimmed(script, log), dangerous, tmp_path)

    assert proc.returncode != 0
    assert "PROMETHEUS_MULTIPROC_DIR" in proc.stderr
    assert not log.exists(), log.read_text(encoding="utf-8")


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
    ficheros mmap.

    256m y no 64m (R25): lleno, cada escritura mmap da SIGBUS (no se puede
    atrapar), todos los workers mueren y los que uvicorn respawnea mueren al
    importar — el color queda caído en bucle. El directorio solo crece en la
    vida del contenedor (los counter/histogram de cada worker muerto se
    quedan), ~3.3 MB por vida de worker en el peor caso medido. tmpfs asigna
    páginas perezosamente: el techo no cuesta memoria mientras no se use."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    entries = _service_tmpfs(text, service)
    assert "/run/prometheus:size=256m,mode=1777" in entries, (
        f"{service}: falta 'tmpfs: - /run/prometheus:size=256m,mode=1777' en "
        f"{COMPOSE_PROD.name} (hay: {entries})"
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
