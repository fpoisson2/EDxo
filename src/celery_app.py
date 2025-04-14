# EDxo/src/celery_app.py
import os
import logging # Ajouter l'import logging
from celery import Celery
# PAS d'import de create_app ici au niveau module

logger = logging.getLogger(__name__) # Initialiser un logger pour ce module

# Fonction pour créer l'instance Celery SANS dépendance immédiate à l'app Flask
def make_celery_instance():
    """Crée et configure une instance Celery de base."""
    redis_url = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    backend_url = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')

    celery_instance = Celery(
        # Utiliser un nom logique, par exemple basé sur le package principal si connu
        # ou simplement 'tasks' si c'est le module principal des tâches.
        # Éviter d'utiliser __name__ si ce fichier n'est pas le point d'entrée principal
        # que Celery utilise pour découvrir les tâches.
        'app.tasks', # Pointant vers le module où les tâches sont définies
        broker=redis_url,
        backend=backend_url,
        include=['app.tasks'] # Assurer la découverte explicite
    )

    celery_instance.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='America/New_York', # Adapter si nécessaire
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        # task_ignore_result=False # Décommenter si vous voulez que les résultats soient toujours stockés par défaut
    )

    # Définir la classe de tâche pour le contexte Flask
    class ContextTask(celery_instance.Task):
        abstract = True
        _flask_app = None

        def __call__(self, *args, **kwargs):
            if self._flask_app is None:
                logger.info("Création du contexte Flask pour la tâche Celery...")
                try:
                    from app import create_app
                except ImportError:
                    from main import create_app

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