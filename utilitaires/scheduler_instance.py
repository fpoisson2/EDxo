# utilitaires/scheduler_instance.py
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import logging

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

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler démarré.")
    else:
        logger.info("Scheduler déjà en cours d'exécution.")
        
def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler arrêté.")