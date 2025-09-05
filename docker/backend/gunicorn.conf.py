# gunicorn.conf.py
import os
bind = "0.0.0.0:8000"
worker_class = "eventlet"
workers = int(os.getenv("GUNICORN_WORKERS", "1"))          # luego puedes probar 8
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "2000"))
graceful_timeout = 30
timeout = 120
keepalive = 30
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "200"))
accesslog = "-"
errorlog  = "-"
