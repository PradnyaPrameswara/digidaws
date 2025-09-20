import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.environ.get("GUNICORN_WORKERS", (multiprocessing.cpu_count() * 2) + 1))
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", 50))
preload_app = True
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))
keepalive = 5
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")  # '-' means stdout
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")

# For behind reverse proxy (Nginx) forwarded headers (optional if using proxy params)
forwarded_allow_ips = "*"
