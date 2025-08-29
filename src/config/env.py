from __future__ import annotations
import os
from dotenv import load_dotenv

# Load environment variables once
load_dotenv()

# Exposed settings
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SECRET_KEY = os.getenv("SECRET_KEY")
RECAPTCHA_PUBLIC_KEY = os.getenv("RECAPTCHA_PUBLIC_KEY")
RECAPTCHA_PRIVATE_KEY = os.getenv("RECAPTCHA_PRIVATE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_SECTION = os.getenv("OPENAI_MODEL_SECTION", "gpt-5")
OPENAI_MODEL_EXTRACTION = os.getenv("OPENAI_MODEL_EXTRACTION", "gpt-5-mini")
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
GUNICORN_WORKER_ID = os.getenv("GUNICORN_WORKER_ID")
CELERY_WORKER = os.getenv("CELERY_WORKER")


def validate() -> None:
    """Raise a RuntimeError if required environment variables are missing."""
    missing = [name for name, value in {
        'SECRET_KEY': SECRET_KEY,
        'RECAPTCHA_PUBLIC_KEY': RECAPTCHA_PUBLIC_KEY,
        'RECAPTCHA_PRIVATE_KEY': RECAPTCHA_PRIVATE_KEY,
    }.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
