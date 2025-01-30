import os
import logging
from sqlalchemy import text

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import after logging setup
from app import create_app
from utils.scheduler_instance import start_scheduler, schedule_backup
from app.models import db

# Create the application instance
app = create_app()

# Only start scheduler on the main worker
worker_id = os.getenv('GUNICORN_WORKER_ID')
is_primary_worker = worker_id == '0' or worker_id is None

if is_primary_worker:
    try:
        # Initialize scheduler
        start_scheduler()
        
        # Setup backups if configured
        with app.app_context():
            result = db.session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
            )).fetchone()
            
            if result:
                schedule_backup(app)
                logger.info("✅ Backup scheduling initialized")
            else:
                logger.warning("⚠️ Table 'backup_config' not found, backups disabled")
                
    except Exception as e:
        logger.error(f"❌ Error during initialization: {e}")

if __name__ == "__main__":
    # This block only runs when executing directly (not through Gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=True)