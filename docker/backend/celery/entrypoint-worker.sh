#!/bin/sh
set -e

cd /app

echo "[celery-worker] Esperando a que la DB esté lista..."
python -m itcj2.cli.main core check-db

# sync-tasks solo en el worker principal. Los workers secundarios (p.ej. el de
# 'reports') ponen CELERY_SKIP_SYNC=1 para no re-sincronizar al arrancar.
if [ "${CELERY_SKIP_SYNC:-0}" != "1" ]; then
  echo "[celery-worker] Sincronizando TaskDefinitions..."
  python -m itcj2.cli.main celery sync-tasks || echo "Advertencia: sync-tasks falló, continuando..."
fi

echo "[celery-worker] Iniciando worker Celery (queues=${CELERY_QUEUES:-default,reports,notifications})..."
exec celery -A itcj2.celery_app worker \
  --loglevel=info \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-4}" \
  --queues="${CELERY_QUEUES:-default,reports,notifications}" \
  --hostname="${CELERY_HOSTNAME:-worker}@%h"
