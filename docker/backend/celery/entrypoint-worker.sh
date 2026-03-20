#!/bin/sh
set -e

cd /app

echo "[celery-worker] Esperando a que la DB esté lista..."
python -m itcj2.cli.main core check-db

echo "[celery-worker] Sincronizando TaskDefinitions..."
python -m itcj2.cli.main celery sync-tasks || echo "Advertencia: sync-tasks falló, continuando..."

echo "[celery-worker] Iniciando worker Celery..."
exec celery -A itcj2.celery_app worker \
  --loglevel=info \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-4}" \
  --queues=default,reports,notifications \
  --hostname="worker@%h"
