# utilitaires/scheduler_instance.py
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Créer une instance unique du planificateur
scheduler = BackgroundScheduler(timezone=pytz.UTC)

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
