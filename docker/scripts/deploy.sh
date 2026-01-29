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

# -- 1.1 Guardar manifiesto de estaticos ANTES del pull (Pilar 3) --
OLD_MANIFEST=""
if [ -f "static-manifest.json" ]; then
    OLD_MANIFEST=$(cat static-manifest.json)
    echo ">>> Manifiesto anterior guardado para comparacion."
fi

# -- 2. Actualizar codigo --
echo ">>> Actualizando codigo desde GitHub..."
git fetch origin
git reset --hard origin/main

# -- 2.1 Generar manifiesto de estaticos (Pilar 2) --
echo ">>> Generando manifiesto de archivos estaticos..."
# Asegurar que el archivo existe (Docker falla si intenta montar un archivo inexistente)
if [ ! -f "static-manifest.json" ]; then
    echo "{}" > static-manifest.json
fi
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

# -- 7.0.1. Asegurar que upstream.conf existe (primer deploy o volumen vacío) --
# El volumen nginx_upstream puede estar vacío, necesitamos crear el archivo
if ! docker compose -f "$COMPOSE_FILE" exec -T nginx test -f /etc/nginx/conf.d/upstream.conf 2>/dev/null; then
    echo ">>> Creando upstream.conf inicial apuntando a backend-$NEW..."
    INITIAL_UPSTREAM="# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $NEW

upstream backend {
    ip_hash;
    server backend-${NEW}:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}"
    docker compose -f "$COMPOSE_FILE" exec -T nginx sh -c "echo '$INITIAL_UPSTREAM' > /etc/nginx/conf.d/upstream.conf"
    docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload
fi

# -- 7.1. Verificar que el nuevo backend es alcanzable desde nginx --
echo ">>> Verificando que backend-$NEW es alcanzable desde Nginx..."
DNS_RETRIES=10
DNS_OK=false
for i in $(seq 1 $DNS_RETRIES); do
    if docker compose -f "$COMPOSE_FILE" exec -T nginx wget -q --spider --timeout=3 "http://backend-${NEW}:8000/health" 2>/dev/null; then
        DNS_OK=true
        echo "    backend-$NEW es alcanzable."
        break
    fi
    echo "    Intento $i/$DNS_RETRIES - Esperando resolución DNS de backend-$NEW..."
    sleep 2
done

if [ "$DNS_OK" != "true" ]; then
    echo "ERROR: Nginx no puede alcanzar backend-$NEW. Abortando cambio de upstream."
    echo ">>> El backend viejo ($ACTIVE) sigue sirviendo trafico."
    # Limpiamos el nuevo backend fallido
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" stop "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" rm -f "backend-$NEW"
    exit 1
fi

# -- 8. Cambiar Nginx al nuevo backend --
echo ">>> Actualizando upstream de Nginx a backend-$NEW..."

# Guardar en archivo local para referencia/backup
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

# Escribir directamente DENTRO del contenedor nginx (evita problemas de bind mount)
UPSTREAM_CONTENT="# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $NEW

upstream backend {
    ip_hash;
    server backend-${NEW}:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}"

docker compose -f "$COMPOSE_FILE" exec -T nginx sh -c "echo '$UPSTREAM_CONTENT' > /etc/nginx/conf.d/upstream.conf"

# Verificar que la configuracion es valida antes de reload
if ! docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -t > /dev/null 2>&1; then
    echo "ERROR: Configuracion de Nginx invalida. Restaurando upstream anterior..."
    
    UPSTREAM_RESTORE="# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $ACTIVE

upstream backend {
    ip_hash;
    server backend-${ACTIVE}:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}"
    docker compose -f "$COMPOSE_FILE" exec -T nginx sh -c "echo '$UPSTREAM_RESTORE' > /etc/nginx/conf.d/upstream.conf"
    
    cat > "$UPSTREAM_FILE" <<NGINX_EOF
# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $ACTIVE

upstream backend {
    ip_hash;
    server backend-${ACTIVE}:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
NGINX_EOF
    echo ">>> Upstream restaurado a backend-$ACTIVE. Limpiando backend-$NEW..."
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" stop "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" rm -f "backend-$NEW"
    exit 1
fi

# Reload graceful - NO causa downtime, las conexiones existentes continuan
echo ">>> Recargando Nginx (graceful reload, zero-downtime)..."
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

# -- 12. Notificar cambios de estaticos via WebSocket (Pilar 3) --
if [ -n "$OLD_MANIFEST" ]; then
    echo ">>> Comparando manifiestos de estaticos..."
    python3 docker/scripts/diff-static-manifest.py \
        --old-manifest <(echo "$OLD_MANIFEST") \
        --new-manifest static-manifest.json \
        --notify-url "http://localhost:8080/api/core/v1/deploy/static-update" \
        || echo "WARN: No se pudo notificar cambios de estaticos (el deploy continua)."
else
    echo ">>> Primer deploy, no hay manifiesto anterior para comparar."
fi

echo ""
echo ">>> Estado final de contenedores:"
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "==========================================="
echo ">>> Deploy completado: $ACTIVE -> $NEW"
echo ">>> CERO downtime - Redis y PostgreSQL nunca se tocaron"
echo "==========================================="
