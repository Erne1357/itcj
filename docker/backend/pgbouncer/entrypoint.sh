#!/bin/sh
# entrypoint.sh — pgBouncer
# Genera /tmp/pgbouncer/userlist.txt desde variables de entorno
# y arranca pgBouncer. Se usa en lugar del entrypoint por defecto
# de la imagen oficial pgbouncer/pgbouncer.
set -e

# Verificar variables requeridas
: "${POSTGRES_USER:?Variable POSTGRES_USER no definida}"
: "${POSTGRES_PASSWORD:?Variable POSTGRES_PASSWORD no definida}"

echo "[pgBouncer] Generando userlist.txt..."
mkdir -p /tmp/pgbouncer

# userlist.txt — una entrada por línea: "usuario" "password"
# Se almacena en texto plano para que pgBouncer pueda realizar
# autenticación SCRAM-SHA-256 con PostgreSQL 16+.
printf '"%s" "%s"\n' "${POSTGRES_USER}" "${POSTGRES_PASSWORD}" > /tmp/pgbouncer/userlist.txt
chmod 600 /tmp/pgbouncer/userlist.txt
chown -R pgb:pgb /tmp/pgbouncer

echo "[pgBouncer] Configuración lista. Pool mode: transaction"
echo "[pgBouncer] Iniciando pgBouncer en 0.0.0.0:5432..."

# Ejecutar como usuario pgb (1.21+ no permite ejecutar como root)
exec su-exec pgb /usr/bin/pgbouncer /etc/pgbouncer/pgbouncer.ini
