# EDxo/src/celery_app.py
import logging
import os

from src.utils.logging_config import setup_logging, get_logger

setup_logging(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))
logger = get_logger(__name__)

from celery import Celery
from src.config.env import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
# PAS d'import de create_app ici au niveau module

# Fonction pour créer l'instance Celery SANS dépendance immédiate à l'app Flask
def make_celery_instance():
    """Crée et configure une instance Celery de base."""
    redis_url = CELERY_BROKER_URL
    backend_url = CELERY_RESULT_BACKEND

    celery_instance = Celery(
        # Nom logique de l'application Celery (à des fins de logs)
        'app',
        broker=redis_url,
        backend=backend_url,
        # Importer le package des tâches tel qu'il est disponible lorsque
        # vous lancez la commande depuis le dossier `src/` (guides du repo).
        # Le nom de tâche effectif est figé via le décorateur `name=...`.
        include=['src.app.tasks', 'app.tasks']
    )

    celery_instance.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='America/New_York', # Adapter si nécessaire
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        task_ignore_result=False,  # Stocker les états pour permettre le suivi depuis le frontend
        # Marquer explicitement les tâches comme STARTED dès leur prise en charge par un worker
        task_track_started=True,
        # File par défaut explicite pour éviter toute ambiguïté de routage
        task_default_queue='celery'
    )

    # Définir la classe de tâche pour le contexte Flask
    class ContextTask(celery_instance.Task):
        abstract = True
        _flask_app = None

        def __call__(self, *args, **kwargs):
            if self._flask_app is None:
                logger.info("Création du contexte Flask pour la tâche Celery...")
                from app import create_app

                # --- CORRECTION ICI ---
                # N'utilisez pas config_name si create_app ne l'accepte pas.
                # Passez testing=True si nécessaire pour les tests, sinon rien.
                # Supposons que create_app gère la config via FLASK_ENV ou autre.
                ContextTask._flask_app = create_app() # Appeler sans config_name
                # --- FIN CORRECTION ---

                # Utiliser un logger pour confirmer la config chargée par create_app si besoin
                logger.info(f"Contexte Flask créé (ENV: {ContextTask._flask_app.config.get('ENV', 'N/A')}, DEBUG: {ContextTask._flask_app.config.get('DEBUG', 'N/A')})")

            with self._flask_app.app_context():
                try:
                    return super().__call__(*args, **kwargs)
                except Exception as task_exc:
                     logger.error(f"Erreur non capturée dans l'exécution de la tâche {self.name}: {task_exc}", exc_info=True)
                     raise

    celery_instance.Task = ContextTask
    return celery_instance

# Créer l'instance globale Celery qui sera importée ailleurs
# Ceci n'appelle PAS create_app()
celery = make_celery_instance()

# Fonction pour mettre à jour la conf Celery depuis l'app Flask (appelée dans __init__.py)
def init_celery(app):
     """Met à jour la configuration Celery avec celle de l'app Flask."""
     # Utiliser les valeurs de l'app Flask pour surcharger les valeurs par défaut/env var
     celery.conf.broker_url = app.config.get('CELERY_BROKER_URL', celery.conf.broker_url)
     celery.conf.result_backend = app.config.get('CELERY_RESULT_BACKEND', celery.conf.result_backend)
     celery.conf.update(app.config.get('CELERY', {})) # Pour d'autres clés CELERY_*
     logger.info("Configuration Celery mise à jour depuis l'app Flask.")
     # Optionnel : Lier la journalisation Celery à celle de Flask ? (Plus complexe)
     return celery
