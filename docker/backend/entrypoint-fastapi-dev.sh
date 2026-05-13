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
echo "Ejecutando migraciones Alembic..."
alembic -c migrations/alembic.ini upgrade head

# ── Uvicorn con hot-reload ─────────────────────────────────────────────
echo "Iniciando FastAPI (Uvicorn dev con --reload)..."
exec uvicorn asgi:app \
  --host 0.0.0.0 \
  --port 8001 \
  --reload \
  --log-level info
