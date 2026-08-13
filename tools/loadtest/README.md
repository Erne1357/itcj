# Banco de pruebas de carga (ensayo del camino completo)

Reproduce **en local** la cadena de producción, incluida la capa que no se puede
tocar en el server sin arriesgar: el nginx del HOST.

```
:8090 (replica del nginx host, MISMOS limit_req/limit_conn)
   └─> nginx del compose dev
         ├─ /socket.io/ -> contenedor `sockets`  (1 worker)
         └─ /*          -> contenedor `backend`  (4 workers en prod)
```

Todas las peticiones salen de la misma IP (el gateway de Docker) = **simulación
de un campus tras NAT**, que es el escenario que importa para AgendaTec.

Correr esto antes de cada periodo de alta demanda. Resultados y conclusiones del
último ensayo: `docs/infra/RUNBOOK_workers.md` §3.bis y §3.ter.

## Preparar

```bash
# 1) stack dev arriba (ya trae el split backend/sockets)
docker compose -f docker/compose/docker-compose.dev.yml up -d

# 2) replica del nginx del host
docker run -d --name itcj-hostsim --network itcj_default -p 8090:80 \
  -v "$PWD/tools/loadtest/nginx.hostsim.v5.conf:/etc/nginx/nginx.conf:ro" nginx:alpine

# 3) cliente de carga (la imagen de la app + aiohttp, que solo necesita el cliente)
docker run -d --name itcj-flood --network itcj_default --env-file .env \
  -v "$PWD:/app" -w /app -e PYTHONPATH=/app --entrypoint /bin/bash \
  itcj-backend -c "pip install -q aiohttp && sleep 3600"

# 4) token de prueba
docker exec itcj-backend-1 sh -c "cd /app && PYTHONPATH=/app python -c \
  \"from itcj2.core.utils.jwt_tools import encode_jwt; print(encode_jwt({'sub':'1','role':'admin'}))\""
```

## Pruebas

| Script | Dónde corre | Qué mide |
|---|---|---|
| `limit_probe.py ws 50 8090` | host | Cuántos WebSockets acepta una IP antes del 429 (`limit_conn`) |
| `limit_probe.py burst 100 8090` | host | Cuántos GET seguidos sobreviven a `limit_req` |
| `pageload_conc.py 60 8090 <token>` | host | N usuarios SIMULTÁNEOS cargando una página en frío (HTML + estáticos) |
| `bench.py 8104 20 10 <token>` | host | Throughput y p95 de un tier HTTP (para A/B 1 vs 4 workers) |
| `socket_flood.py 500 40 notify` | `itcj-flood` | N sockets reales del namespace global de notificaciones |
| `socket_flood.py 300 30 slots 2026-08-20` | `itcj-flood` | N alumnos entrando a AgendaTec (connect + `join_day`, 2 golpes a BD c/u) |
| `sampler.py 35` | `itcj-sockets-1` | **Pico** de conexiones a pgbouncer durante la ráfaga |
| `measure.py` | cualquier contenedor | Foto puntual de conexiones a BD y sockets entrantes |

Ejemplo de la prueba que más importa (¿se llena la pool con el herd?):

```bash
docker cp tools/loadtest/sampler.py      itcj-sockets-1:/tmp/sampler.py
docker cp tools/loadtest/socket_flood.py itcj-flood:/tmp/socket_flood.py

docker exec -d itcj-sockets-1 python /tmp/sampler.py 35
docker exec -d itcj-flood     python /tmp/socket_flood.py 300 30 slots 2026-08-20
sleep 40
docker exec itcj-sockets-1 cat /tmp/sampler.json     # pico_db vs DB_POOL_SIZE+DB_MAX_OVERFLOW
docker logs itcj-sockets-1 2>&1 | grep -c QueuePool  # debe ser 0
```

## Trampas que ya costaron una medición falsa

- **`ss` y `netstat` NO existen** en la imagen. `ss ... | grep -c` sobre salida
  vacía devuelve `0` y parece "cero conexiones a la BD" cuando en realidad no se
  midió nada. Por eso `measure.py`/`sampler.py` leen `/proc/net/tcp` directo.
  Regla: validar la sonda con un contador que **sí** deba subir (los sockets
  entrantes en `:8001`) antes de creerle al que da 0.
- **`error.log` es symlink a `/dev/stderr`** en la imagen `nginx`: hacerle `grep`
  cuelga el comando. Usar `docker logs itcj-hostsim`.
- **El pico dura 2-3 s.** Medir después de la ráfaga da 0. Hay que muestrear
  durante (de ahí `sampler.py`).
- **El generador se satura antes que el servidor.** Con 600 clientes en un solo
  proceso Python, el cuello fue el cliente: el pico de BD *bajó*. Si los números
  mejoran al subir la carga, sospechar del banco, no celebrar.
- Los `req/s` de este banco **no son capacidad de producción** (Docker Desktop,
  código en bind-mount, BD de dev). Sirven para comparar A contra B en el mismo
  banco.

## Limpiar

```bash
docker rm -f itcj-hostsim itcj-flood
docker exec itcj-redis-1 redis-cli del presence:notify:students presence:notify:staff presence:notify:admins
```
