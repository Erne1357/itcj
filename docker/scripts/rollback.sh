#!/usr/bin/env bash
# docker/scripts/rollback.sh
#
# Rollback de CÓDIGO a la imagen inmutable previa (2.4), sin rebuild ni git.
# Levanta el color inactivo con itcj2-backend:<prev-sha>, mueve nginx a él, y
# detiene el backend malo. Mismo mecanismo blue/green que deploy.sh.
#
# ⚠️ NO revierte la base de datos. Si el deploy malo aplicó una migración
#    destructiva, el código viejo puede romper contra el esquema nuevo. En ese
#    caso: restaurar el dump pre-deploy (deploy.sh lo crea) y/o alembic downgrade
#    ANTES de confiar en el rollback. Por eso conviene expand/contract.
#
# Uso: ./rollback.sh            (rollback a la imagen previa)
#      ./rollback.sh <sha>      (rollback a una imagen específica existente)
set -euo pipefail

PROJECT_DIR="/home/cuaderno/ITCJ"
COMPOSE_FILE="docker/compose/docker-compose.prod.yml"
UPSTREAM_FILE="docker/nginx/upstream.conf"
STATE_FILE="docker/.active-color"
LAST_IMG_FILE="docker/.last-good-image"
PREV_IMG_FILE="docker/.prev-good-image"

cd "$PROJECT_DIR"

# -- 1. Determinar imagen destino --
if [ "${1:-}" != "" ]; then
    TARGET_IMG="$1"
elif [ -f "$PREV_IMG_FILE" ]; then
    TARGET_IMG="$(cat "$PREV_IMG_FILE")"
else
    echo "ERROR: no hay imagen previa (.prev-good-image). Pasa un sha: ./rollback.sh <sha>"
    exit 1
fi

if [ -z "$TARGET_IMG" ]; then
    echo "ERROR: imagen destino vacía."
    exit 1
fi

if ! docker image inspect "itcj2-backend:$TARGET_IMG" > /dev/null 2>&1; then
    echo "ERROR: la imagen itcj2-backend:$TARGET_IMG no existe localmente."
    echo "Imágenes disponibles:"
    docker images itcj2-backend --format '  {{.Tag}} ({{.CreatedSince}})'
    exit 1
fi

export IMAGE_TAG="$TARGET_IMG"

# -- 2. Determinar colores --
if [ -f "$STATE_FILE" ]; then
    ACTIVE="$(cat "$STATE_FILE")"
else
    ACTIVE="blue"
fi
if [ "$ACTIVE" = "blue" ]; then
    TARGET_COLOR="green"
else
    TARGET_COLOR="blue"
fi

echo "==========================================="
echo ">>> ROLLBACK: $ACTIVE (actual) -> $TARGET_COLOR con imagen itcj2-backend:$TARGET_IMG"
echo "==========================================="

# -- 3. Levantar el color destino con la imagen previa (SIN build) --
echo ">>> Levantando backend-$TARGET_COLOR con itcj2-backend:$TARGET_IMG..."
docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" up -d --no-build "backend-$TARGET_COLOR"

# -- 4. Esperar health del color destino --
echo ">>> Esperando health de backend-$TARGET_COLOR..."
RETRIES=30
HEALTHY=false
for i in $(seq 1 $RETRIES); do
    CID="$(docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" ps -q "backend-$TARGET_COLOR" 2>/dev/null || echo "")"
    if [ -n "$CID" ]; then
        STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$CID" 2>/dev/null || echo "starting")"
        if [ "$STATUS" = "healthy" ]; then HEALTHY=true; break; fi
        echo "    Intento $i/$RETRIES - Estado: $STATUS"
    else
        echo "    Intento $i/$RETRIES - Contenedor aún no disponible..."
    fi
    sleep 2
done

if [ "$HEALTHY" != "true" ]; then
    echo "ERROR: backend-$TARGET_COLOR no pasó health. Abortando rollback (el backend actual sigue sirviendo)."
    docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" logs --tail=40 "backend-$TARGET_COLOR"
    docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" stop "backend-$TARGET_COLOR"
    docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" rm -f "backend-$TARGET_COLOR"
    exit 1
fi
echo ">>> backend-$TARGET_COLOR healthy."

# -- 5. Verificar alcanzable (/ready) --
CID="$(docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" ps -q "backend-$TARGET_COLOR" 2>/dev/null | head -1)"
BACKEND_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CID" 2>/dev/null | head -1)"
if [ -z "$BACKEND_IP" ] || ! curl -sf --max-time 3 "http://$BACKEND_IP:8001/ready" > /dev/null 2>&1; then
    echo "ERROR: backend-$TARGET_COLOR no responde /ready. Abortando."
    docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" stop "backend-$TARGET_COLOR"
    docker compose -f "$COMPOSE_FILE" --profile "$TARGET_COLOR" rm -f "backend-$TARGET_COLOR"
    exit 1
fi
echo ">>> backend-$TARGET_COLOR responde /ready (IP $BACKEND_IP)."

# -- 6. Mover nginx al color destino --
echo ">>> Actualizando upstream de Nginx a backend-$TARGET_COLOR..."
cat > "$UPSTREAM_FILE" <<NGINX_EOF
# Generado por rollback.sh - NO EDITAR
# Backend activo: $TARGET_COLOR (rollback a itcj2-backend:$TARGET_IMG)

upstream backend {
    ip_hash;
    server backend-${TARGET_COLOR}:8001 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
NGINX_EOF

if ! docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -t > /dev/null 2>&1; then
    echo "ERROR: config de Nginx inválida tras el rollback. Revisa $UPSTREAM_FILE."
    exit 1
fi
docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload
echo ">>> Nginx recargado. Tráfico en backend-$TARGET_COLOR."

# -- 7. Recrear Celery con la imagen previa (consistencia de código) --
echo ">>> Recreando Celery con itcj2-backend:$TARGET_IMG..."
docker compose -f "$COMPOSE_FILE" up -d --no-build --force-recreate \
    celery-worker celery-worker-reports celery-beat

# -- 8. Drenar y detener el backend malo --
echo ">>> Esperando 30s para drenar backend-$ACTIVE..."
sleep 30
if docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" ps -q "backend-$ACTIVE" 2>/dev/null | grep -q .; then
    docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" stop "backend-$ACTIVE"
    docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" rm -f "backend-$ACTIVE"
fi

# -- 9. Guardar estado --
echo "$TARGET_COLOR" > "$STATE_FILE"
echo "$TARGET_IMG" > "$LAST_IMG_FILE"

echo "==========================================="
echo ">>> ROLLBACK completado: ahora activo backend-$TARGET_COLOR (itcj2-backend:$TARGET_IMG)"
echo ">>> RECUERDA: la BD NO se revirtió. Si hubo migración destructiva, revisa el esquema."
echo "==========================================="
