import pytest
from utils.auth import load_user
from app.models import User, db


def test_load_user_valid_id(app):
    """load_user should return a User instance for a valid ID."""
    with app.app_context():
        user = User(username="tester", password="secret", role="invite")
        db.session.add(user)
        db.session.commit()
        loaded = load_user(user.id)
        assert isinstance(loaded, User)
        assert loaded.id == user.id


def test_load_user_invalid_id(app):
    """load_user should return None for a non-existent ID."""
    with app.app_context():
        loaded = load_user(99999)
        assert loaded is None
