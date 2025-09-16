import requests
from flask import current_app, request


def verify_recaptcha(token: str) -> bool:
    """Verify a reCAPTCHA v3 token using Google's API.

    Args:
        token: The reCAPTCHA token provided by the client.

    Returns:
        bool: ``True`` if the verification succeeds and the score meets the
        configured threshold, ``False`` otherwise.
    """
    if current_app.config.get("RECAPTCHA_DISABLED"):
        return True

    if not token:
        return False

    verify_url = "https://www.google.com/recaptcha/api/siteverify"
    payload = {
        "secret": current_app.config.get("RECAPTCHA_SECRET_KEY"),
        "response": token,
        "remoteip": request.remote_addr,
    }
    try:
        response = requests.post(verify_url, data=payload, timeout=5)
        result = response.json()
    except Exception:
        return False

    threshold = current_app.config.get("RECAPTCHA_THRESHOLD", 0.5)
    return result.get("success", False) and result.get("score", 0) >= threshold
