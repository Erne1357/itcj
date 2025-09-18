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

# Ejecutar migraciones después de la restauración
echo "Ejecutando migraciones..."
flask db upgrade || exit 1

# Lanzar Gunicorn con Eventlet (soporte WebSockets)
exec gunicorn \
  --config /etc/gunicorn/gunicorn.conf.py \
  wsgi:app
