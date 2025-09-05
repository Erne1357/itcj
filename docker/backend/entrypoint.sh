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

# Lanzar Gunicorn con Eventlet (soporte WebSockets)
exec gunicorn \
  --config /etc/gunicorn/gunicorn.conf.py \
  wsgi:app