# gunicorn.conf.py
import os

# Bind
bind = "0.0.0.0:8000"

# Worker class para WebSocket (Socket.IO)
# IMPORTANTE: Eventlet con Socket.IO solo soporta 1 worker por proceso.
# Para escalar, usar múltiples contenedores Docker con un load balancer
# y sticky sessions (ip_hash o cookie-based).
worker_class = "eventlet"
workers = 1

# Conexiones simultáneas por worker (eventlet puede manejar miles)
# Para 500-2000 usuarios concurrentes, 10000 es suficiente
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "10000"))

# Timeouts para WebSocket (conexiones de larga duración)
timeout = 300  # 5 minutos para requests normales
graceful_timeout = 30
keepalive = 75

# Worker lifecycle
# max_requests=0 evita reinicios que desconectarían WebSockets
max_requests = 0
max_requests_jitter = 0

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
