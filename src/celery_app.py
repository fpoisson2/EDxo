from celery import Celery

def make_celery():
    from app import create_app
    flask_app = create_app()

    # Retrieve the broker and backend using legacy keys if necessary
    broker_url = flask_app.config.get("CELERY_BROKER_URL") or flask_app.config.get("broker_url")
    result_backend = flask_app.config.get("CELERY_RESULT_BACKEND") or flask_app.config.get("result_backend")
    
    celery = Celery(
        flask_app.import_name,
        broker=broker_url,
        backend=result_backend,
        include=['app.tasks']
    )

    # Convert legacy keys to new keys
    new_conf = {}
    for key, value in flask_app.config.items():
        if key.startswith("CELERY_"):
            # Remove the prefix and convert to lower-case.
            new_key = key[len("CELERY_"):].lower()
            new_conf[new_key] = value
        else:
            new_conf[key] = value

    celery.conf.update(new_conf)

    # Set the new setting to avoid the warning about broker connection retries.
    celery.conf.update({
        'broker_connection_retry_on_startup': True,
    })

    # Wrap tasks so they run within the Flask app context.
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    return celery

celery = make_celery()
