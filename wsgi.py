from app import app
from utilitaires.scheduler_instance import start_scheduler, schedule_backup

if __name__ == "__main__":
    # Initialize scheduler before workers are forked
    schedule_backup(app)
    start_scheduler()
    app.run()