import os
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import logging
from datetime import datetime
from models import BackupConfig
from functools import wraps
import threading

from utils import send_backup_email  # Move to top with other imports

_scheduler_lock = threading.Lock()

def with_scheduler_lock(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _scheduler_lock:
            return f(*args, **kwargs)
    return wrapper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone=pytz.UTC,
    job_defaults={
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': 3600
    }
)

def is_main_process():
    worker_id = os.getenv('GUNICORN_WORKER_ID')
    return worker_id == '0' or worker_id is None

def start_scheduler():
    if not scheduler.running and is_main_process():
        logger.info(f"Current jobs before start: {scheduler.get_jobs()}")
        scheduler.start()
        logger.info(f"Current jobs after start: {scheduler.get_jobs()}")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler arrêté.")


@with_scheduler_lock
def schedule_backup(app):
    logger.info("Starting schedule_backup function")
    logger.info(f"Current jobs before scheduling: {scheduler.get_jobs()}")
    logger.info(f"Scheduler running status: {scheduler.running}")

    if not is_main_process():
        logger.info(f"Process info - Name: {multiprocessing.current_process().name}")
        return

    with app.app_context():
        config = BackupConfig.query.first()
        logger.info(f"Backup config: {config.__dict__ if config else None}")
        
        if config and config.enabled:
            try:
                backup_time = datetime.strptime(config.backup_time, '%H:%M').time()
                logger.info(f"Scheduled backup time: {backup_time}")
                
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
                logger.info(f"All jobs after scheduling: {scheduler.get_jobs()}")
                for job in scheduler.get_jobs():
                    logger.info(f"Job {job.id} next run: {job.next_run_time}")
                    
            except Exception as e:
                logger.error(f"Scheduling error: {e}", exc_info=True)

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
def job_error_handler(event):
    logger.error(f"Job failed: {event.job_id}, error: {event.exception}")

def job_executed_handler(event):
    logger.info(f"Job executed: {event.job_id}, runtime: {event.scheduled_run_time}")

scheduler.add_listener(job_error_handler, EVENT_JOB_ERROR)
scheduler.add_listener(job_executed_handler, EVENT_JOB_EXECUTED)