"""WSGI entrypoint for running the EDxo app with Gunicorn."""

import logging
import os
import sys

# Ensure the ``src`` directory is on ``sys.path`` before project imports
sys.path.insert(0, os.path.dirname(__file__))

from .utils.logging_config import setup_logging

setup_logging(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))

from .app import create_app  # <- import relatif

# Create the Flask application instance
application = create_app()
app = application  # exposer 'app' et 'application' est OK

if __name__ == "__main__":
    application.run()
