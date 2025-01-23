from utilitaires.scheduler_instance import start_scheduler, schedule_backup

def on_starting(server):
    from app import app  # Import the Flask app
    with app.app_context():
        from utilitaires.scheduler_instance import start_scheduler, schedule_backup
        schedule_backup(app)
        start_scheduler()