#!/bin/sh
set -e

cd /app

echo "[celery-beat] Esperando a que la DB esté lista..."
python -m itcj2.cli.main core check-db

echo "[celery-beat] Iniciando Celery Beat (DatabaseScheduler)..."
exec celery -A itcj2.celery_app beat \
  --loglevel=info \
  --scheduler itcj2.tasks.scheduler:DatabaseScheduler \
  --pidfile=/tmp/celerybeat.pid
