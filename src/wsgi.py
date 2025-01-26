from app.app import create_app  # or however you import your Flask app factory
from utils.scheduler_instance import start_scheduler, schedule_backup

app = create_app()

# Start the scheduler and schedule the backup *after* the app is created.
start_scheduler()
schedule_backup(app)

if __name__ == "__main__":
    # For local/dev runs (e.g. python wsgi.py), usually you do:
    app.run(host="0.0.0.0", port=5000)
