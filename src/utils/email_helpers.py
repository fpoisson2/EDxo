"""Utility functions for email operations."""

import requests
from flask import current_app, url_for

from app.models import MailgunConfig


def send_reset_email(user_email: str, token: str) -> None:
    """Send a password reset email via Mailgun.

    Args:
        user_email: Recipient email address.
        token: Password reset token.
    """
    reset_url = url_for("main.reset_password", token=token, _external=True)
    subject = "Réinitialisation de votre mot de passe"
    text = (
        "Bonjour,\n\n"
        "Pour réinitialiser votre mot de passe, veuillez cliquer sur le lien suivant :\n"
        f"{reset_url}\n\n"
        "Si vous n'avez pas demandé cette réinitialisation, veuillez ignorer ce message."
    )

    mailgun_config = MailgunConfig.query.first()
    if not mailgun_config:
        current_app.logger.error("La configuration Mailgun est manquante!")
        return

    url = f"https://api.mailgun.net/v3/{mailgun_config.mailgun_domain}/messages"
    auth = ("api", mailgun_config.mailgun_api_key)
    data = {
        "from": "EDxo <no-reply@edxo.ca>",
        "to": user_email,
        "subject": subject,
        "text": text,
    }
    response = requests.post(url, auth=auth, data=data)
    if response.status_code != 200:
        current_app.logger.error("Erreur lors de l'envoi de l'email: %s", response.text)
