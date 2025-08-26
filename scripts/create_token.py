"""Utility script to generate a Gmail API token."""

from src.utils.google_api import build_gmail_service

if __name__ == "__main__":
    build_gmail_service()
    print("✅ Token généré et sauvegardé dans token.json")
