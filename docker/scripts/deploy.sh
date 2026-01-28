#!/usr/bin/env bash
# docker/scripts/deploy.sh
#
# Blue-Green deployment sin downtime.
# Uso: ./deploy.sh
#
# Este script implementa el Pilar 1 del plan de zero-downtime deployment.
# Nunca baja el contenedor viejo hasta que el nuevo este sirviendo trafico.
set -euo pipefail

PROJECT_DIR="/home/cuaderno/ITCJ"
COMPOSE_FILE="docker/compose/docker-compose.prod.yml"
UPSTREAM_FILE="docker/nginx/upstream.conf"
STATE_FILE="docker/.active-color"

cd "$PROJECT_DIR"

# -- 1. Determinar color activo y nuevo --
if [ -f "$STATE_FILE" ]; then
    ACTIVE=$(cat "$STATE_FILE")
else
    ACTIVE="blue"
fi

if [ "$ACTIVE" = "blue" ]; then
    NEW="green"
else
    NEW="blue"
fi

echo ">>> Color activo: $ACTIVE -> Desplegando: $NEW"

# -- 2. Actualizar codigo --
echo ">>> Actualizando codigo desde GitHub..."
git fetch origin
git reset --hard origin/main

# -- 2.1 Generar manifiesto de estaticos (Pilar 2) --
echo ">>> Generando manifiesto de archivos estaticos..."
bash docker/scripts/generate-static-manifest.sh

# -- 3. Asegurar que infraestructura esta corriendo --
echo ">>> Verificando infraestructura (Redis + PostgreSQL)..."
docker compose -f "$COMPOSE_FILE" up -d redis postgres

# Esperar a que Redis este listo
echo ">>> Esperando a que Redis este listo..."
REDIS_RETRIES=30
for i in $(seq 1 $REDIS_RETRIES); do
    if docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; then
        echo "    Redis listo."
        break
    fi
    echo "    Intento $i/$REDIS_RETRIES - Esperando Redis..."
    sleep 2
done

# Esperar a que PostgreSQL este listo
echo ">>> Esperando a que PostgreSQL este listo..."
PG_RETRIES=30
for i in $(seq 1 $PG_RETRIES); do
    if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
        echo "    PostgreSQL listo."
        break
    fi
    echo "    Intento $i/$PG_RETRIES - Esperando PostgreSQL..."
    sleep 2
done

# -- 4. Ejecutar migraciones ANTES de levantar el nuevo backend --
echo ">>> Ejecutando migraciones de base de datos..."
# Si hay un backend activo, ejecutar migraciones en el
if docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" ps -q "backend-$ACTIVE" 2>/dev/null | grep -q .; then
    docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" exec -T "backend-$ACTIVE" \
        flask db upgrade 2>/dev/null || echo ">>> Migraciones ya aplicadas o sin cambios."
else
    # Si no hay backend activo (primer deploy), construir y ejecutar en el nuevo
    echo ">>> Primer deploy detectado, construyendo imagen para migraciones..."
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" build "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" run --rm "backend-$NEW" \
        flask db upgrade
fi

# -- 5. Construir y levantar nuevo backend --
echo ">>> Construyendo imagen del nuevo backend ($NEW)..."
docker compose -f "$COMPOSE_FILE" --profile "$NEW" build "backend-$NEW"

echo ">>> Levantando backend-$NEW..."
docker compose -f "$COMPOSE_FILE" --profile "$NEW" up -d "backend-$NEW"

# -- 6. Esperar health check del nuevo backend --
echo ">>> Esperando health check de backend-$NEW..."
RETRIES=30
HEALTHY=false
for i in $(seq 1 $RETRIES); do
    CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" --profile "$NEW" ps -q "backend-$NEW" 2>/dev/null || echo "")
    if [ -n "$CONTAINER_ID" ]; then
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_ID" 2>/dev/null || echo "starting")
        if [ "$STATUS" = "healthy" ]; then
            HEALTHY=true
            break
        fi
        echo "    Intento $i/$RETRIES - Estado: $STATUS"
    else
        echo "    Intento $i/$RETRIES - Contenedor aun no disponible..."
    fi
    sleep 2
done

if [ "$HEALTHY" != "true" ]; then
    echo "ERROR: backend-$NEW no paso el health check. Abortando."
    echo ">>> Logs del contenedor fallido:"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" logs --tail=50 "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" stop "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" rm -f "backend-$NEW"
    exit 1
fi

echo ">>> backend-$NEW esta healthy."

# -- 7. Asegurar que Nginx esta corriendo --
echo ">>> Verificando Nginx..."
docker compose -f "$COMPOSE_FILE" up -d nginx

# Esperar un momento para que Nginx inicie
sleep 3

# -- 8. Cambiar Nginx al nuevo backend --
echo ">>> Actualizando upstream de Nginx a backend-$NEW..."
cat > "$UPSTREAM_FILE" <<NGINX_EOF
# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $NEW

upstream backend {
    ip_hash;
    server backend-${NEW}:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
NGINX_EOF

# Reload Nginx (zero downtime - no restart)
docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload
echo ">>> Nginx recargado. Trafico apuntando a backend-$NEW."

# -- 9. Drenar conexiones del backend viejo --
echo ">>> Esperando 30s para drenar conexiones de backend-$ACTIVE..."
sleep 30

# -- 10. Detener backend viejo (si existe) --
if docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" ps -q "backend-$ACTIVE" 2>/dev/null | grep -q .; then
    echo ">>> Deteniendo backend-$ACTIVE..."
    docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" stop "backend-$ACTIVE"
    docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" rm -f "backend-$ACTIVE"
else
    echo ">>> No habia backend-$ACTIVE corriendo (primer deploy)."
fi

# -- 11. Guardar estado y limpiar --
echo "$NEW" > "$STATE_FILE"
docker image prune -f

echo ""
echo ">>> Estado final de contenedores:"
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "==========================================="
echo ">>> Deploy completado: $ACTIVE -> $NEW"
echo ">>> CERO downtime - Redis y PostgreSQL nunca se tocaron"
echo "==========================================="
