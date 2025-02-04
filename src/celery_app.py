from celery import Celery

def make_celery():
    # Import create_app lazily to avoid circular imports.
    from app import create_app
    flask_app = create_app()

    # Do not push a permanent app context here.
    # Instead, rely on our custom ContextTask to create one for each task.
    
    celery = Celery(
        flask_app.import_name,
        broker=flask_app.config.get("CELERY_BROKER_URL"),
        backend=flask_app.config.get("CELERY_RESULT_BACKEND"),
        # Explicitly include the tasks module so Celery registers tasks from it.
        include=['app.tasks']
    )
    celery.conf.update(flask_app.config)

    # Wrap tasks so that they run within the Flask application context.
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    return celery

celery = make_celery()
