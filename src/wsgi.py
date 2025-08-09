"""WSGI entrypoint for running the EDxo app with Gunicorn."""

import os
import sys

# Ensure the ``src`` directory is on ``sys.path`` so absolute imports like
# ``extensions`` resolve when the app is loaded via ``src.wsgi``.
sys.path.insert(0, os.path.dirname(__file__))

from .app import create_app  # <- import relatif

# Create the Flask application instance
application = create_app()
app = application  # exposer 'app' et 'application' est OK

if __name__ == "__main__":
    application.run()
