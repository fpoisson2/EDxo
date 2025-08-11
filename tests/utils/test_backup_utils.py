import logging

import requests

from src.utils.backup_utils import send_backup_email
from app.models import MailgunConfig
from src.app import db


def test_send_backup_email_posts_correct_request(tmp_path, monkeypatch, app):
    db_file = tmp_path / "dummy.db"
    db_file.write_bytes(b"test content")

    with app.app_context():
        db.session.add(MailgunConfig(mailgun_domain="test.domain", mailgun_api_key="key"))
        db.session.commit()

    captured = {}

    def fake_post(url, auth=None, data=None, files=None):
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["files"] = files

        class Resp:
            status_code = 200
            text = "OK"

        return Resp()

    monkeypatch.setattr(requests, "post", fake_post)

    with app.app_context():
        send_backup_email("dest@example.com", str(db_file))

    assert captured["url"] == "https://api.mailgun.net/v3/test.domain/messages"
    assert captured["auth"] == ("api", "key")
    assert captured["data"]["to"] == "dest@example.com"
    assert captured["data"]["from"] == "EDxo <francis.poisson@edxo.ca>"
    assert captured["files"]["attachment"][0] == "backup.db"
    assert captured["files"]["attachment"][1] == b"test content"


def test_send_backup_email_without_config_logs_error(tmp_path, caplog, monkeypatch, app):
    db_file = tmp_path / "dummy.db"
    db_file.write_bytes(b"content")

    def fake_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called")

    monkeypatch.setattr(requests, "post", fake_post)

    with app.app_context():
        with caplog.at_level(logging.ERROR, logger="src.utils.backup_utils"):
            send_backup_email("dest@example.com", str(db_file))

    assert "Mailgun configuration not found!" in caplog.text
