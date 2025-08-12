import logging

import requests
from flask import Flask


def get_scheduler_instance() -> "BackgroundScheduler":
    """Create and configure an APScheduler instance.

    Returns:
        BackgroundScheduler: Scheduler configured for UTC with safe defaults.
    """

    from apscheduler.schedulers.background import BackgroundScheduler
    import pytz

    return BackgroundScheduler(
        timezone=pytz.UTC,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )


def send_backup_email_with_context(app: Flask, recipient_email: str, db_path: str) -> None:
    """Send a backup email using the provided application context."""

    with app.app_context():
        send_backup_email(recipient_email, db_path)


def send_backup_email(recipient_email: str, db_path: str) -> None:
    """Email the database backup file to the given recipient."""

    logger = logging.getLogger(__name__)
    logger.info("Starting backup email to %s", recipient_email)

    with open(db_path, "rb") as f:
        file_data = f.read()

    from app.models import MailgunConfig

    mailgun_config = MailgunConfig.query.first()
    if not mailgun_config:
        logger.error("Mailgun configuration not found!")
        return

    url = f"https://api.mailgun.net/v3/{mailgun_config.mailgun_domain}/messages"
    auth = ("api", mailgun_config.mailgun_api_key)

    files = {"attachment": ("backup.db", file_data)}

    data = {
        "from": "EDxo <francis.poisson@edxo.ca>",
        "to": recipient_email,
        "subject": "BD EDxo",
        "text": "Bonjour, voici la dernière version de la BD de EDxo",
    }

    response = requests.post(url, auth=auth, data=data, files=files)

    if response.status_code == 200:
        logger.info("Email sent successfully!")
    else:
        logger.error("Failed to send email: %s - %s", response.status_code, response.text)
