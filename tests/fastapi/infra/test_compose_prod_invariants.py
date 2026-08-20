"""Invariantes del compose de producción (tier HTTP / tier de sockets).

Estas reglas ya rompieron producción una vez cada una; el compose es el único
lugar donde se declaran y nada las verificaba. No necesitan BD ni datos: leen
archivos del repo, así que corren igual en CI (esquema limpio, sin DML).

No se usa PyYAML a propósito: NO está en requirements.txt y CI instala solo eso
(`pip install -r requirements.txt`), así que un `import yaml` sería un
ImportError en el gate. El parser de abajo es mínimo y solo entiende la forma
`- CLAVE=valor` dentro de `environment:`, que es como está escrito el archivo.
"""
from pathlib import Path

from itcj2.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PROD = REPO_ROOT / "docker" / "compose" / "docker-compose.prod.yml"
PGBOUNCER_INI = REPO_ROOT / "docker" / "backend" / "pgbouncer" / "pgbouncer.ini"

HTTP_SERVICES = ("backend-blue", "backend-green")

# Hilos del threadpool de anyio por worker: FastAPI corre ahí los endpoints
# `def` (la mayoría de este proyecto) y cada uno pide una conexión de la pool.
ANYIO_THREADPOOL_PER_WORKER = 40

# Techo del executor por defecto de asyncio: min(32, os.cpu_count() + 4).
# Los handlers de socket pegan a la BD vía asyncio.to_thread.
ASYNCIO_EXECUTOR_CEILING = 32


def _service_env(service: str) -> dict[str, str]:
    """Variables del bloque ``environment:`` de un servicio del compose."""
    env: dict[str, str] = {}
    in_service = False
    in_env = False

    for line in COMPOSE_PROD.read_text(encoding="utf-8").splitlines():
        # Nombre de servicio = clave con indentación de exactamente 2 espacios.
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            in_service = line.strip().rstrip(":") == service
            in_env = False
            continue
        if not in_service:
            continue

        stripped = line.strip()
        if stripped == "environment:":
            in_env = True
            continue
        if not in_env:
            continue

        if stripped.startswith("- "):
            item = stripped[2:]
            if "=" in item:
                key, value = item.split("=", 1)
                env[key.strip()] = value.strip()
        elif stripped and not stripped.startswith("#"):
            in_env = False  # empezó otra clave del servicio

    assert env, f"no se encontró el bloque environment de '{service}' en {COMPOSE_PROD.name}"
    return env


def _max_client_conn() -> int:
    for line in PGBOUNCER_INI.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("max_client_conn"):
            return int(line.split("=", 1)[1].strip())
    raise AssertionError("max_client_conn no está en pgbouncer.ini")


def test_tier_http_cumple_la_invariante_del_pool():
    """``DB_POOL_SIZE + DB_MAX_OVERFLOW >= 40`` POR WORKER.

    Con la CPU capada (``cpus: 4.0``) los requests tardan más, se acumulan más
    en vuelo por worker y una pool menor al threadpool se agota: espera el
    ``pool_timeout=10`` y sale HTTP 500. Medido con 30 concurrentes: pool 8+4
    dio 4.7 req/s, p95 20s y 5 × HTTP 500; pool 10+30 dio 235 req/s sin un solo
    error. Repartir la pool entre workers es justo lo que rompe la invariante.
    """
    for service in HTTP_SERVICES:
        env = _service_env(service)
        assert env["APP_ROLE"] == "http", f"{service}: APP_ROLE debe ser http"
        total = int(env["DB_POOL_SIZE"]) + int(env["DB_MAX_OVERFLOW"])
        assert total >= ANYIO_THREADPOOL_PER_WORKER, (
            f"{service}: pool+overflow = {total} < {ANYIO_THREADPOOL_PER_WORKER} "
            "(threadpool de anyio por worker) -> QueuePool timeout = HTTP 500"
        )


def test_tier_sockets_corre_en_un_solo_proceso():
    """El tier de Socket.IO NO se escala.

    La sesión engine.io (el ``sid`` del handshake, el buffer de polling) es
    estado en memoria del proceso. Con N procesos, el POST de polling cae en uno
    que no conoce ese sid y la conexión truena. ``AsyncRedisManager`` reparte
    *broadcasts*, no sesiones.
    """
    env = _service_env("sockets")
    assert env["APP_ROLE"] == "socket"
    assert env["UVICORN_WORKERS"] == "1", (
        "el tier de sockets debe ser UN proceso; escalarlo rompe el polling"
    )


def test_tier_sockets_pool_supera_el_executor_de_asyncio():
    """La pool del contenedor de sockets debe quedar por encima del executor.

    Si el techo real de concurrencia (min(32, cpu_count+4)) es mayor que la
    pool, la pool es el cuello y las esperas se comen el ``pool_timeout``.
    Medido con 300 alumnos entrando a /slots a la vez: con 10+10 el pico se
    clavaba en 20/20 (pool 100% saturada, sin margen).
    """
    env = _service_env("sockets")
    total = int(env["DB_POOL_SIZE"]) + int(env["DB_MAX_OVERFLOW"])
    assert total >= ASYNCIO_EXECUTOR_CEILING, (
        f"sockets: pool+overflow = {total} < {ASYNCIO_EXECUTOR_CEILING}"
    )


def test_presupuesto_de_conexiones_cabe_en_pgbouncer():
    """Todas las conexiones CLIENTE juntas deben caber en ``max_client_conn``.

    Se cuenta el peor caso real: la ventana del blue/green, donde los DOS
    colores del tier HTTP están arriba a la vez. Los servicios de Celery no
    declaran pool, así que usan el default de ``Settings``.

    Es el corolario que el runbook de workers deja anotado: si algún día se
    suben los workers, hay que revisar ``max_client_conn`` (o bajar el
    threadpool de anyio explícitamente). Este test lo cobra solo.
    """
    http_env = _service_env("backend-blue")
    por_worker = int(http_env["DB_POOL_SIZE"]) + int(http_env["DB_MAX_OVERFLOW"])
    http_por_color = int(http_env["UVICORN_WORKERS"]) * por_worker

    sockets_env = _service_env("sockets")
    sockets_total = int(sockets_env["DB_POOL_SIZE"]) + int(sockets_env["DB_MAX_OVERFLOW"])

    defaults = Settings()
    celery_total = 3 * (defaults.DB_POOL_SIZE + defaults.DB_MAX_OVERFLOW)  # worker, reports, beat

    peor_caso = 2 * http_por_color + sockets_total + celery_total
    limite = _max_client_conn()
    assert peor_caso <= limite, (
        f"presupuesto {peor_caso} > max_client_conn {limite} "
        f"(HTTP {http_por_color} x2 colores + sockets {sockets_total} + celery {celery_total})"
    )
