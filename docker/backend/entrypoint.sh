#!/usr/bin/env bash
set -euo pipefail

# Verificación que wsgi.py existe en el directorio montado
if [ ! -f "/app/wsgi.py" ]; then
  echo "ERROR: /app/wsgi.py no existe. Estructura actual:"
  ls -la /app || true
  exit 1
fi

# Cambiar al directorio de la app
cd /app

# Verificar si ya se ha restaurado la base de datos
#if [ ! -f /var/lib/postgresql/data/itcj.db ]; then
 # echo "Restaurando la base de datos desde el dump..."
  # Ejecutar el script de restauración (asegurando que está disponible el archivo)
  #/docker-entrypoint-initdb.d/init-itcj.sh
#fi

echo "Verificando conexión a Redis..."
python3 << 'PYEOF'
import redis
import os
import sys

try:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    r = redis.from_url(redis_url)
    r.ping()
    print(f"✓ Redis conectado exitosamente: {redis_url}")
except Exception as e:
    print(f"✗ ERROR: No se puede conectar a Redis: {e}")
    sys.exit(1)
PYEOF

# Ejecutar migraciones con conexión DIRECTA a Postgres (nunca a pgBouncer).
# Alembic usa advisory locks que son persistentes a nivel de conexión;
# en transaction pooling mode, pgBouncer puede cambiar la conexión
# subyacente entre transacciones y romper el lock.
# MIGRATE_DATABASE_URL apunta a postgres:5432 (bypass de pgBouncer).
echo "Ejecutando migraciones (conexión directa a Postgres)..."
DATABASE_URL="${MIGRATE_DATABASE_URL:-$DATABASE_URL}" flask db upgrade || exit 1

# Lanzar Gunicorn con Eventlet (soporte WebSockets)
exec gunicorn \
  --config /etc/gunicorn/gunicorn.conf.py \
  wsgi:app
