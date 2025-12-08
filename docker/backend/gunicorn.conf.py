# gunicorn.conf.py
import os

# Bind
bind = "0.0.0.0:8000"

# Worker class compatible con SSE (Server-Sent Events)
worker_class = "eventlet"
workers = 1  # Eventlet es single-threaded pero maneja múltiples conexiones

# Conexiones simultáneas por worker
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "5000"))

# Timeouts - AUMENTADOS para SSE (conexiones de larga duración)
timeout = 7200  # 2 horas - necesario para SSE
graceful_timeout = 30
keepalive = 75

# Worker lifecycle - NO reiniciar workers con SSE activo
max_requests = 0  # Deshabilitado para mantener conexiones SSE
max_requests_jitter = 0

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
