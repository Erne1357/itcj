#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "/app/asgi.py" ]; then
  echo "ERROR: /app/asgi.py no existe. Estructura actual:"
  ls -la /app || true
  exit 1
fi

cd /app
export PYTHONPATH="/app:${PYTHONPATH:-}"

# ── Esperar Redis ──────────────────────────────────────────────────────
echo "Esperando a Redis..."
python3 << 'PYEOF'
import os, sys, time
import redis

url = os.getenv("REDIS_URL", "redis://redis:6379/0")
deadline = time.time() + 60
while True:
    try:
        redis.from_url(url).ping()
        print("✓ Redis listo")
        break
    except Exception as e:
        if time.time() > deadline:
            print(f"✗ Redis no respondió en 60s: {e}")
            sys.exit(1)
        time.sleep(1)
PYEOF

# ── Migraciones Alembic ────────────────────────────────────────────────
# RUN_MIGRATIONS=0 en el contenedor `sockets`: dos procesos corriendo
# `alembic upgrade head` a la vez compiten por la misma tabla de versiones.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "Ejecutando migraciones Alembic..."
  alembic -c migrations/alembic.ini upgrade head
else
  echo "RUN_MIGRATIONS=0 — saltando Alembic (las corre el contenedor backend)."
fi

# ── Uvicorn con hot-reload ─────────────────────────────────────────────
# --reload implica 1 worker; dev reproduce el SPLIT de prod (APP_ROLE), no el
# número de workers.
echo "Iniciando FastAPI (Uvicorn dev con --reload) — APP_ROLE=${APP_ROLE:-all}..."
exec uvicorn asgi:app \
  --host 0.0.0.0 \
  --port 8001 \
  --reload \
  --log-level info
