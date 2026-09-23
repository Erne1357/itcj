#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "/app/asgi.py" ]; then
  echo "ERROR: /app/asgi.py no existe. Estructura actual:"
  ls -la /app || true
  exit 1
fi

cd /app

# Asegurar que /app esté en PYTHONPATH
export PYTHONPATH="/app:${PYTHONPATH:-}"

# Verificar Redis
echo "Verificando conexión a Redis..."
python3 << 'PYEOF'
import redis, os, sys
try:
    r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    r.ping()
    print(f"✓ Redis conectado")
except Exception as e:
    print(f"✗ Redis ERROR: {e}")
    sys.exit(1)
PYEOF

# NOTA (1.5): las migraciones YA NO corren aquí. Se ejecutan como un paso
# explícito y único en deploy.sh (con pg_dump previo), para evitar que blue y
# green compitan por migrar al bootear y que un reinicio simple mueva el esquema.

# ── Rol del proceso + nº de workers (F2.1) ─────────────────────────────
# APP_ROLE=http   → 4 workers, sin Socket.IO montado (backend-blue/green)
# APP_ROLE=socket → 1 worker, sirve /socket.io/ (contenedor `sockets`)
# APP_ROLE=all    → default histórico: un proceso hace todo
# Guardarraíl: cualquier rol que sirva Socket.IO va a 1 worker SÍ o SÍ. La
# sesión engine.io vive en memoria del proceso; con N workers el polling cae
# en procesos distintos y la conexión truena.
APP_ROLE="${APP_ROLE:-all}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

if [ "$APP_ROLE" != "http" ] && [ "$UVICORN_WORKERS" != "1" ]; then
  echo "WARN: APP_ROLE=$APP_ROLE sirve Socket.IO -> forzando UVICORN_WORKERS=1 (pedido: $UVICORN_WORKERS)"
  UVICORN_WORKERS=1
fi

# Confiar en X-Forwarded-For solo si se configura explícitamente. Vacío =
# request.client.host es la IP de nginx (comportamiento actual). Ver
# docs/infra/RUNBOOK_workers.md: activarlo REQUIERE que el nginx del host
# reescriba XFF con $remote_addr, si no la IP se vuelve falsificable.
FORWARDED_ARGS=""
if [ -n "${UVICORN_FORWARDED_ALLOW_IPS:-}" ]; then
  FORWARDED_ARGS="--forwarded-allow-ips=${UVICORN_FORWARDED_ALLOW_IPS}"
  echo "Uvicorn: confiando X-Forwarded-For de ${UVICORN_FORWARDED_ALLOW_IPS}"
fi

echo "Iniciando FastAPI (Uvicorn) — APP_ROLE=$APP_ROLE, workers=$UVICORN_WORKERS..."

# ── prometheus_client en modo multiproceso (F2b) ───────────────────────
# Con --workers 4 cada worker es un proceso, y el registro normal de
# prometheus_client daria el numero de UNO al azar (mal, no ausente). Los
# mmap van a un tmpfs propio, no a /dev/shm: el compose solo declara
# shm_size en postgres, asi que aqui /dev/shm son los 64 MB por defecto de
# Docker y hay que compartirlos con lo que sea.
# Se VACIA el directorio, nunca se borra (R23): en prod es el PUNTO DE
# MONTAJE del tmpfs del compose, y rmdir sobre un punto de montaje da EBUSY
# incluso a root; con set -e el contenedor moriria aqui, antes de uvicorn, y
# no arrancaria ningun color ni sockets. Vaciarlo al arrancar importa si esta
# ruta alguna vez NO fuera un tmpfs: los ficheros de la vida anterior del
# contenedor se seguirian sumando al total. Dentro de una misma vida, los
# Gauge livesum de un worker muerto los retira metrics.reap_dead_workers()
# en cada scrape (mark_process_dead); sus Counter e Histogram se quedan a
# proposito, porque sus peticiones cuentan.
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/run/prometheus}"
# Guarda: con "/" (o "//", "/x/..") el find de abajo vaciaria el contenedor
# entero. realpath -m resuelve la ruta sin exigir que exista.
if [ "$(realpath -m -- "$PROMETHEUS_MULTIPROC_DIR")" = "/" ]; then
  echo "ERROR: PROMETHEUS_MULTIPROC_DIR no puede ser la raiz (vale: '$PROMETHEUS_MULTIPROC_DIR')" >&2
  exit 1
fi
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
find "${PROMETHEUS_MULTIPROC_DIR:?}" -mindepth 1 -delete

# --no-access-log: la línea por petición ya la emite ObservabilityMiddleware
# (JSON, con la ruta plantillada y la duración). Con el access log de uvicorn
# serían dos líneas por petición: el doble de volumen en Loki y un doble
# conteo garantizado en cualquier panel.
exec uvicorn asgi:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers "$UVICORN_WORKERS" \
  ${FORWARDED_ARGS} \
  --log-level info \
  --no-access-log
