#!/bin/bash
# Captura estado de pool cada minuto. Correr en background:
#   nohup ./scripts/diagnose_pool.sh > /tmp/pool_history.log 2>&1 &
# Cuando backend caiga, revisar /tmp/pool_history.log para ver evolución.

cd ~/ITCJ
COMPOSE="docker compose -f docker/compose/docker-compose.prod.yml"

while true; do
  TS=$(date +"%Y-%m-%d %H:%M:%S")
  echo "===== $TS ====="

  echo "--- pg_stat_activity counts ---"
  $COMPOSE exec -T postgres psql -U postgres itcj -t -c "
    SELECT state, count(*)
    FROM pg_stat_activity
    WHERE datname='itcj'
    GROUP BY state;" 2>/dev/null

  echo "--- queries activas > 5s ---"
  $COMPOSE exec -T postgres psql -U postgres itcj -t -c "
    SELECT pid, state,
           extract(epoch from (now() - query_start))::int AS secs,
           left(query, 150)
    FROM pg_stat_activity
    WHERE datname='itcj'
      AND state != 'idle'
      AND now() - query_start > interval '5 seconds'
    ORDER BY secs DESC LIMIT 10;" 2>/dev/null

  echo "--- idle in transaction (leak signal) ---"
  $COMPOSE exec -T postgres psql -U postgres itcj -t -c "
    SELECT pid,
           extract(epoch from (now() - state_change))::int AS idle_secs,
           left(query, 150)
    FROM pg_stat_activity
    WHERE datname='itcj' AND state='idle in transaction'
    ORDER BY idle_secs DESC LIMIT 10;" 2>/dev/null

  echo "--- SQLAlchemy pool backend-green ---"
  $COMPOSE exec -T backend-green python -c \
    "from itcj2.database import engine; print(engine.pool.status())" 2>/dev/null

  echo ""
  sleep 60
done
