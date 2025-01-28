def on_starting(server):
    for i, worker in enumerate(server.WORKERS):
        worker.env["GUNICORN_WORKER_ID"] = str(i)

bind = "0.0.0.0:5000"
workers = 3
worker_class = "sync"
timeout = 500