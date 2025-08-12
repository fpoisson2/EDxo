import pytest

from src.utils.scheduler_instance import scheduler, schedule_backup
from src.app import db
from src.app.models import BackupConfig


def _create_config(app, enabled: bool) -> None:
    with app.app_context():
        app.config.setdefault("DB_PATH", "test.db")
        config = BackupConfig(
            email="test@example.com",
            frequency="Daily",
            backup_time="12:30",
            enabled=enabled,
        )
        db.session.add(config)
        db.session.commit()


def test_schedule_backup_enabled(app):
    scheduler.remove_all_jobs()
    _create_config(app, True)
    schedule_backup(app)
    assert scheduler.get_job("daily_backup") is not None
    scheduler.remove_all_jobs()


def test_schedule_backup_disabled(app):
    scheduler.remove_all_jobs()
    _create_config(app, False)
    schedule_backup(app)
    assert scheduler.get_job("daily_backup") is None
    scheduler.remove_all_jobs()
