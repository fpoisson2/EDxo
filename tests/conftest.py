import os
import pytest
import sys

# Ensure that the application's source code is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from src.app import create_app, db

@pytest.fixture
def app():
    """
    Create and configure an instance of the application for testing.
    The database is created before tests and dropped after.
    """
    app = create_app(testing=True)
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """
    Provides a test client for simulating HTTP requests.
    """
    return app.test_client()
