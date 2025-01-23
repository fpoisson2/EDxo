from app import app
from utilitaires.scheduler_instance import start_scheduler, schedule_backup

schedule_backup(app)
start_scheduler()

if __name__ == "__main__":
    app.run()