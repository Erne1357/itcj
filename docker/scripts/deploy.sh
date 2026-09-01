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

# -- 1.2 Generador de upstream.conf (2.1: DOS upstreams) --
# backend = tier HTTP blue/green (4 workers uvicorn). sockets = contenedor
# unico de Socket.IO (1 worker), no tiene color.
# OJO: nginx resuelve los nombres de upstream AL CARGAR la config, asi que
# ambos contenedores deben existir antes de levantar/recargar nginx, y hay que
# recargar si alguno se recrea (cambia de IP).
write_upstream() {
    local color="$1"
    cat > "$UPSTREAM_FILE" <<NGINX_EOF
# Archivo generado automaticamente por deploy.sh
# NO EDITAR MANUALMENTE - se sobrescribe en cada deploy
# Backend activo: $color

upstream backend {
    ip_hash;
    server backend-${color}:8001 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

# Socket.IO: proceso unico (la sesion engine.io es estado en memoria).
upstream sockets {
    server sockets:8001 max_fails=3 fail_timeout=30s;
}
NGINX_EOF
}

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

# -- 2.0 Tag de imagen inmutable por commit (2.3) --
# La imagen lleva el codigo horneado (itcj2/asgi.py/migrations), no bind-mount.
# IMAGE_TAG = sha corto; el compose la referencia via ${IMAGE_TAG}. Habilita
# rollback a una imagen previa sin rebuild (ver rollback.sh, 2.4).
export IMAGE_TAG="$(git rev-parse --short HEAD)"
echo ">>> Imagen objetivo: itcj2-backend:$IMAGE_TAG"

# -- 2.1 Generar manifiesto de estaticos (Pilar 2) --
echo ">>> Generando manifiesto de archivos estaticos..."
# Asegurar que el archivo existe (Docker falla si intenta montar un archivo inexistente)
if [ ! -f "static-manifest.json" ]; then
    echo "{}" > static-manifest.json
fi
bash docker/scripts/generate-static-manifest.sh

# -- 3. Asegurar que infraestructura esta corriendo --
echo ">>> Verificando infraestructura (Redis + PostgreSQL + pgBouncer)..."
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

# Construir y levantar pgBouncer (se reconstruye solo si el Dockerfile cambio)
echo ">>> Levantando pgBouncer..."
docker compose -f "$COMPOSE_FILE" up -d --build pgbouncer

# Esperar a que pgBouncer este listo
echo ">>> Esperando a que pgBouncer este listo..."
PGB_RETRIES=20
for i in $(seq 1 $PGB_RETRIES); do
    CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" ps -q pgbouncer 2>/dev/null || echo "")
    if [ -n "$CONTAINER_ID" ]; then
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_ID" 2>/dev/null || echo "starting")
        if [ "$STATUS" = "healthy" ]; then
            echo "    pgBouncer listo."
            break
        fi
    fi
    echo "    Intento $i/$PGB_RETRIES - Esperando pgBouncer..."
    sleep 2
done

# -- NOTA: En el PRIMER deploy, ejecutar manualmente DESPUÉS de levantar la infraestructura:
#    docker compose -f "$COMPOSE_FILE" --profile blue run --rm backend-blue \
#        python -m itcj2.cli.main core init-tasks
# Esto inserta permisos y definiciones de tareas en la DB. Solo se necesita una vez.
# -----------------------------------------------------------------------------------------

# -- 4.0 Backup de la BD ANTES de migrar (Pilar 1.5) --
# Una migración destructiva sin respaldo fresco es irreversible. Hacemos un
# pg_dump comprimido a un directorio FUERA del bind-mount de los contenedores.
echo ">>> Backup de la BD antes de migrar..."
BACKUP_DIR="/home/cuaderno/backups"
mkdir -p "$BACKUP_DIR"
if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U postgres -Fc itcj \
        > "$BACKUP_DIR/itcj_predeploy_$(date +%F_%H%M%S).dump" 2>/dev/null; then
    echo "    Backup creado en $BACKUP_DIR."
    # Conservar solo los últimos 10 backups pre-deploy.
    ls -1t "$BACKUP_DIR"/itcj_predeploy_*.dump 2>/dev/null | tail -n +11 | xargs -r rm -f
else
    echo "    WARN: no se pudo crear el backup pre-migración (¿postgres arriba?)."
    echo "    Abortando deploy: no migramos sin respaldo fresco."
    rm -f "$BACKUP_DIR"/itcj_predeploy_*.dump.tmp 2>/dev/null || true
    exit 1
fi

# -- 4. Construir la imagen nueva y migrar EN ELLA (el entrypoint ya NO migra) --
#
# SIEMPRE en la imagen NUEVA, nunca en el contenedor activo. Desde 334d2b6
# (`feat(infra): imagen inmutable con código horneado`) `migrations/` va horneada
# en la imagen y NO se bind-montea: el contenedor activo corre la imagen del
# deploy ANTERIOR, así que no contiene las revisiones que se acaban de traer con
# el `git reset --hard` de arriba. Un `alembic upgrade head` ahí no ve nada nuevo
# y sale con 0 — la migración queda SIN APLICAR y el backend nuevo se promueve
# contra el esquema viejo.
#
# Con una tabla nueva eso solo rompe la feature; con una COLUMNA nueva sobre una
# tabla existente rompe la app entera, porque SQLAlchemy hace SELECT de todas las
# columnas mapeadas: `authenticate()` y cualquier `db.get(User, ...)` tiran
# UndefinedColumn y nadie puede iniciar sesión. Y el health check no lo ataja:
# /ready solo hace `SELECT 1` y un ping a Redis, no toca ninguna tabla del
# dominio, así que el backend roto pasa y nginx conmuta hacia él.
#
# `run --rm` levanta un contenedor desechable con la imagen nueva y migra ANTES
# de que exista tráfico sobre ella. El build va aquí (no en el paso 5) porque la
# migración lo necesita; el `up -d` de abajo reusa esa misma imagen.
echo ">>> Construyendo imagen del nuevo backend ($NEW)..."
docker compose -f "$COMPOSE_FILE" --profile "$NEW" build "backend-$NEW"

echo ">>> Ejecutando migraciones de base de datos (en la imagen $NEW)..."
docker compose -f "$COMPOSE_FILE" --profile "$NEW" run --rm \
    --entrypoint "" \
    -e PYTHONPATH=/app \
    "backend-$NEW" \
    bash -c "cd /app && alembic -c migrations/alembic.ini upgrade head"

# -- 5. Levantar nuevo backend (la imagen ya se construyó en el paso 4) --
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

# -- 7.0. Asegurar que el contenedor de sockets existe (2.1) --
# nginx resuelve `upstream sockets { server sockets:8001; }` al cargar la
# config: si el contenedor no existe, nginx NO arranca. Aqui solo lo creamos
# si falta (primer deploy tras el split); la recreacion con la imagen nueva va
# al final, despues de promover el backend.
if ! docker compose -f "$COMPOSE_FILE" ps -q sockets 2>/dev/null | grep -q .; then
    echo ">>> Levantando contenedor de sockets (no existia)..."
    docker compose -f "$COMPOSE_FILE" up -d sockets
fi

# -- 7. Regenerar upstream.conf ANTES de levantar Nginx --
# CRÍTICO: Si el archivo no existe, Docker crea un directorio vacío y el bind mount se rompe.
# Se regenera SIEMPRE (no solo si falta): un upstream.conf viejo sin el bloque
# `sockets` haria fallar `nginx -t` y el contenedor no arrancaria.
if docker compose -f "$COMPOSE_FILE" --profile "$ACTIVE" ps -q "backend-$ACTIVE" 2>/dev/null | grep -q .; then
    INITIAL_BACKEND="$ACTIVE"
else
    INITIAL_BACKEND="$NEW"
fi
write_upstream "$INITIAL_BACKEND"
echo ">>> upstream.conf regenerado (backend-$INITIAL_BACKEND + sockets)."

# -- 7.1. Asegurar que Nginx esta corriendo --
echo ">>> Verificando Nginx..."
docker compose -f "$COMPOSE_FILE" up -d nginx

# Esperar un momento para que Nginx inicie
sleep 3

# -- 7.2. Verificar que el nuevo backend es alcanzable en la red Docker --
# Usamos la IP interna del contenedor desde el host, evitando dependencias de DNS
# dentro del contenedor nginx (que acaba de recrearse y puede tener lag DNS).
echo ">>> Verificando que backend-$NEW es alcanzable en la red Docker..."
REACH_RETRIES=15
REACH_OK=false
CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" --profile "$NEW" ps -q "backend-$NEW" 2>/dev/null | head -1)
for i in $(seq 1 $REACH_RETRIES); do
    if [ -n "$CONTAINER_ID" ]; then
        BACKEND_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_ID" 2>/dev/null | head -1)
        if [ -n "$BACKEND_IP" ] && curl -sf --max-time 3 "http://$BACKEND_IP:8001/ready" > /dev/null 2>&1; then
            REACH_OK=true
            echo "    backend-$NEW es alcanzable (IP: $BACKEND_IP)."
            break
        fi
    fi
    echo "    Intento $i/$REACH_RETRIES - Esperando conectividad con backend-$NEW..."
    sleep 2
done

if [ "$REACH_OK" != "true" ]; then
    echo "ERROR: backend-$NEW no es alcanzable en la red Docker. Abortando cambio de upstream."
    echo ">>> El backend viejo ($ACTIVE) sigue sirviendo trafico."
    echo ">>> Logs del backend fallido:"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" logs --tail=30 "backend-$NEW"
    # Limpiamos el nuevo backend fallido
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" stop "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" rm -f "backend-$NEW"
    exit 1
fi

# -- 8. Cambiar Nginx al nuevo backend --
echo ">>> Actualizando upstream de Nginx a backend-$NEW..."

# Actualizar archivo en el host (bind mount sin :ro lo sincroniza automaticamente)
write_upstream "$NEW"

# Verificar que la configuracion es valida antes de reload
if ! docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -t > /dev/null 2>&1; then
    echo "ERROR: Configuracion de Nginx invalida. Restaurando upstream anterior..."
    write_upstream "$ACTIVE"
    echo ">>> Upstream restaurado a backend-$ACTIVE. Limpiando backend-$NEW..."
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" stop "backend-$NEW"
    docker compose -f "$COMPOSE_FILE" --profile "$NEW" rm -f "backend-$NEW"
    exit 1
fi

# Reload graceful - NO causa downtime, las conexiones existentes continuan
echo ">>> Recargando Nginx (graceful reload, zero-downtime)..."
docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload

# -- 8.1. Verificar que nginx realmente está sirviendo desde el nuevo backend --
echo ">>> Verificando que nginx cambió al nuevo backend..."
sleep 1  # Dar tiempo al reload

# Verificar que el archivo dentro del contenedor apunta al backend correcto
CONTAINER_UPSTREAM=$(docker compose -f "$COMPOSE_FILE" exec -T nginx cat /etc/nginx/conf.d/upstream.conf 2>/dev/null || echo "")
if echo "$CONTAINER_UPSTREAM" | grep -q "backend-${NEW}"; then
    echo "    ✓ upstream.conf dentro del contenedor apunta a backend-$NEW"
else
    echo "ERROR: upstream.conf dentro del contenedor NO apunta a backend-$NEW"
    echo "    Contenido actual:"
    echo "$CONTAINER_UPSTREAM"
    echo ""
    echo ">>> ACCIÓN REQUERIDA: Recrear el contenedor de nginx manualmente:"
    echo "    docker compose -f $COMPOSE_FILE up -d --force-recreate nginx"
    exit 1
fi

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

# -- 11.0 Guardar imagen buena para rollback (2.4) --
# .last-good-image = imagen recien promovida; .prev-good-image = la anterior
# (destino del rollback). rollback.sh lee .prev-good-image.
LAST_IMG_FILE="docker/.last-good-image"
PREV_IMG_FILE="docker/.prev-good-image"
if [ -f "$LAST_IMG_FILE" ]; then
    cp "$LAST_IMG_FILE" "$PREV_IMG_FILE"
fi
echo "$IMAGE_TAG" > "$LAST_IMG_FILE"

# Retencion: conservar solo las 5 imagenes itcj2-backend mas nuevas. Las en uso
# no se pueden borrar (rmi falla -> se quedan), por eso el '|| true'.
docker images itcj2-backend --format '{{.Tag}}' | grep -v '^latest$' | tail -n +6 \
    | xargs -r -I{} docker rmi "itcj2-backend:{}" 2>/dev/null || true

docker image prune -f

# -- 11.1 Reconstruir y reiniciar Celery worker/beat (código actualizado) --
# --force-recreate es crítico: sin él Docker omite el restart si la config del compose
# no cambió, y el proceso Python sigue con módulos viejos cacheados en memoria.
echo ">>> Actualizando Celery worker y beat..."
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate celery-worker celery-worker-reports celery-beat
echo ">>> Celery workers (principal + reports) y beat actualizados."

# -- 11.2 Recrear el contenedor de sockets con la imagen nueva (2.1) --
# Es UN solo proceso (no hay blue/green): al recrearlo los WebSockets se caen
# ~1-3s y los clientes reconectan solos. El trafico HTTP no se entera.
# Va AL FINAL, ya con el backend nuevo promovido, para que el codigo de ambos
# tiers coincida el menor tiempo posible.
echo ">>> Recreando contenedor de sockets con itcj2-backend:$IMAGE_TAG..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate sockets

echo ">>> Esperando /ready de sockets..."
SOCK_RETRIES=20
SOCK_OK=false
for i in $(seq 1 $SOCK_RETRIES); do
    SOCK_CID=$(docker compose -f "$COMPOSE_FILE" ps -q sockets 2>/dev/null | head -1)
    if [ -n "$SOCK_CID" ]; then
        SOCK_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$SOCK_CID" 2>/dev/null || echo "starting")
        if [ "$SOCK_STATUS" = "healthy" ]; then
            SOCK_OK=true
            break
        fi
    fi
    echo "    Intento $i/$SOCK_RETRIES - Esperando sockets ($SOCK_STATUS)..."
    sleep 2
done

if [ "$SOCK_OK" != "true" ]; then
    echo "WARN: el contenedor de sockets no paso health. El HTTP sigue OK, pero"
    echo "      los WebSockets estaran caidos. Revisar: docker compose -f $COMPOSE_FILE logs --tail=50 sockets"
    docker compose -f "$COMPOSE_FILE" logs --tail=30 sockets || true
fi

# El contenedor recreado tiene IP nueva y nginx cachea la resolucion del
# upstream al cargar la config: sin este reload, /socket.io/ pega a la IP
# muerta y da 502 hasta el siguiente deploy.
echo ">>> Recargando Nginx para tomar la IP nueva de sockets..."
docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload
echo ">>> Sockets actualizado."

# -- 12. Notificar cambios de estaticos via WebSocket (Pilar 3) --
if [ -n "$OLD_MANIFEST" ]; then
    echo ">>> Comparando manifiestos de estaticos..."
    python3 docker/scripts/diff-static-manifest.py \
        --old-manifest <(echo "$OLD_MANIFEST") \
        --new-manifest static-manifest.json \
        --notify-url "http://localhost:8080/api/core/v2/deploy/static-update" \
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
