import threading
from functools import wraps
import logging
from datetime import datetime
import os
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from models import BackupConfig
from utilitaires.backup_utils import send_backup_email, get_scheduler_instance

scheduler_lock = threading.Lock()
scheduler = get_scheduler_instance()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def with_scheduler_lock(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with scheduler_lock:
            return f(*args, **kwargs)
    return wrapper

def is_main_process():
    # Force True if you want a single worker to do scheduling
    return True

def start_scheduler():
    if not scheduler.running and is_main_process():
        logger.info("Starting scheduler")
        scheduler.start()

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")

@with_scheduler_lock
def schedule_backup(app):
    logger.info("Starting schedule_backup function")
    logger.info(f"Current jobs: {scheduler.get_jobs()}")
    logger.info(f"Scheduler running: {scheduler.running}")

    if not is_main_process():
        return

    with app.app_context():
        config = BackupConfig.query.first()
        logger.info(f"Backup config: {config.__dict__ if config else None}")
        
        if config and config.enabled:
            try:
                backup_time = datetime.strptime(config.backup_time, '%H:%M').time()
                logger.info(f"Scheduled time: {backup_time}")
                
                job_args = {
                    'func': send_backup_email,
                    'trigger': 'cron',
                    'hour': backup_time.hour,
                    'minute': backup_time.minute,
                    'args': [app, config.email, app.config['DB_PATH']],
                    'id': f"{config.frequency.lower()}_backup",
                    'replace_existing': True,
                    'name': f'Backup {config.frequency}'
                }
                
                scheduler.add_job(**job_args)
                logger.info(f"Jobs after scheduling: {scheduler.get_jobs()}")
                for job in scheduler.get_jobs():
                    logger.info(f"Job {job.id} next run: {job.next_run_time}")
                    
            except Exception as e:
                logger.error(f"Scheduling error: {e}", exc_info=True)

def job_error_handler(event):
    logger.error(f"Job failed: {event.job_id}, error: {event.exception}")

def job_executed_handler(event):
    logger.info(f"Job executed: {event.job_id}, runtime: {event.scheduled_run_time}")

scheduler.add_listener(job_error_handler, EVENT_JOB_ERROR)
scheduler.add_listener(job_executed_handler, EVENT_JOB_EXECUTED)