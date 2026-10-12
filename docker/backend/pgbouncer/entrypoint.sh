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

# Rol de solo-monitoreo (opcional). Existe para que el pgbouncer-exporter del
# stack de observabilidad deje de entrar como SUPERUSUARIO: hoy su password
# viaja dentro de una URL en una variable de entorno, o sea legible con
# `docker inspect` por cualquiera del grupo docker, en un host que esta app
# comparte con otra.
#
# Va con guardia y no como variable requerida a proposito: si el .env no las
# trae, pgBouncer arranca exactamente igual que antes. Un `: "${VAR:?}"` aqui
# dejaria la BD sin pooler en el primer deploy que no las tuviera.
#
# El rol tambien tiene que estar en `stats_users` de pgbouncer.ini para leer la
# BD virtual "pgbouncer" (SHOW POOLS/STATS), y existir en Postgres con la MISMA
# password.
if [ -n "${MONITORING_USER:-}" ] && [ -n "${MONITORING_PASSWORD:-}" ]; then
  printf '"%s" "%s"\n' "${MONITORING_USER}" "${MONITORING_PASSWORD}" >> /tmp/pgbouncer/userlist.txt
  echo "[pgBouncer] userlist.txt incluye el rol de monitoreo: ${MONITORING_USER}"
fi
chmod 600 /tmp/pgbouncer/userlist.txt
chown -R pgb:pgb /tmp/pgbouncer

echo "[pgBouncer] Configuración lista. Pool mode: transaction"
echo "[pgBouncer] Iniciando pgBouncer en 0.0.0.0:5432..."

# Ejecutar como usuario pgb (1.21+ no permite ejecutar como root)
exec su-exec pgb /usr/bin/pgbouncer /etc/pgbouncer/pgbouncer.ini
