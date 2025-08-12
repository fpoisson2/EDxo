import logging
import os

from .utils.logging_config import setup_logging

setup_logging(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")))

from .app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
