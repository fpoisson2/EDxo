import os
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import logging
from datetime import datetime
from models import BackupConfig
from functools import wraps
import threading

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
        logger.debug(f"Current jobs before start: {scheduler.get_jobs()}")
        scheduler.start()
        logger.debug(f"Current jobs after start: {scheduler.get_jobs()}")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler arrêté.")


@with_scheduler_lock
def schedule_backup(app):
    if not is_main_process():
        return
    logger.debug("Scheduling backup...")
    if os.getenv('GUNICORN_WORKER_PROCESS_NAME') == 'Worker':
        return

    from utils import send_backup_email
    
    with app.app_context():
        config = BackupConfig.query.first()
        if config and config.enabled:
            try:
                backup_time = datetime.strptime(config.backup_time, '%H:%M').time()
                frequency = config.frequency.lower()
                
                job_id = f"{frequency}_backup"
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                
                job_args = {
                    'func': send_backup_email,
                    'trigger': 'cron',
                    'hour': backup_time.hour,
                    'minute': backup_time.minute,
                    'args': [app, config.email, app.config['DB_PATH']],
                    'id': job_id,
                    'replace_existing': True,
                    'name': f'Backup {frequency}'
                }
                
                if frequency == 'weekly':
                    job_args['day_of_week'] = 'mon'
                elif frequency == 'monthly':
                    job_args['day'] = 1
                
                scheduler.add_job(**job_args)
                logger.info(f"Job de backup planifié: {job_id}")
                
            except Exception as e:
                logger.error(f"Erreur planification: {e}", exc_info=True)