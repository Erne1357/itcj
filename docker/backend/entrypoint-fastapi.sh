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

# Correr migraciones con Alembic directo (sin Flask)
echo "Ejecutando migraciones Alembic..."
alembic -c migrations/alembic.ini upgrade head

echo "Iniciando FastAPI (Uvicorn)..."
exec uvicorn asgi:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 1 \
  --log-level info
