"""Helpers for interacting with Google APIs."""

from __future__ import annotations

import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def build_gmail_service(
    credentials_file: str = "credentials.json",
    token_file: str = "token.json",
):
    """Return an authenticated Gmail API service.

    If the token file is missing or invalid, the OAuth2 flow will be run to
    create a new token.

    Args:
        credentials_file: Path to the OAuth2 client secrets.
        token_file: Path where the OAuth2 token is stored.

    Returns:
        googleapiclient.discovery.Resource: Gmail API service instance.
    """
    creds: Optional[Credentials] = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        with open(token_file, "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)
