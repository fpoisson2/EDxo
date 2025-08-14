"""WSGI entrypoint for running the EDxo app with Gunicorn."""

import importlib
import logging
import os
import sys

# Ensure the ``src`` directory is on ``sys.path`` before project imports
sys.path.insert(0, os.path.dirname(__file__))

from .utils.logging_config import setup_logging

# Recharger explicitement les variables d'environnement projet
env_module = importlib.import_module(".config.env", __package__)
env_module = importlib.reload(env_module)

setup_logging(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))

# Importer dynamiquement l'application après rechargement de la configuration
app_module = importlib.import_module(".app", __package__)
app_module = importlib.reload(app_module)

# Créer l'instance Flask
application = app_module.create_app()
app = application  # exposer 'app' et 'application' est OK

if __name__ == "__main__":
    application.run()
