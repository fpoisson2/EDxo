import logging
import requests
from flask import current_app

def get_scheduler_instance():
    import os
    from apscheduler.schedulers.background import BackgroundScheduler
    import pytz
    return BackgroundScheduler(
        timezone=pytz.UTC,
        job_defaults={
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 3600
        }
    )

def send_backup_email_with_context(app, recipient_email, db_path):
    # Here, 'app' is assumed to be the real Flask application instance.
    with app.app_context():
        send_backup_email(recipient_email, db_path)

def send_backup_email(recipient_email, db_path):
    logger = logging.getLogger(__name__)
    logger.info(f"Starting backup email to {recipient_email}")

    # Read the backup file
    with open(db_path, 'rb') as f:
        file_data = f.read()

    from app.models import MailgunConfig
    # Using current_app requires an active app context!
    mailgun_config = MailgunConfig.query.first()
    if not mailgun_config:
        logger.error("Mailgun configuration not found!")
        return

    url = f"https://api.mailgun.net/v3/{mailgun_config.mailgun_domain}/messages"
    auth = ("api", mailgun_config.mailgun_api_key)

    files = {
        "attachment": ("backup.db", file_data)
    }

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
        logger.error(f"Failed to send email: {response.status_code} - {response.text}")
