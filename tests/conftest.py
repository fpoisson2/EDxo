# tests/conftest.py

import pytest
import sys, os
from pathlib import Path
from flask_wtf.csrf import CSRFProtect
from src.extensions import db, csrf  # Import centralized extensions

sys.path.append(str(Path(__file__).parent.parent / 'src'))
os.environ['TESTING'] = 'True'
from src.app import create_app
from src.app.routes.cours import cours_bp
from src.app.routes.routes import main as main_bp
from src.app.routes.plan_de_cours import plan_de_cours_bp
from src.app.routes.programme import programme_bp
from src.utils.auth import login_manager  # Importer login_manager
from flask_login import current_user
from src.app.models import User, Programme, Department

@pytest.fixture(scope='function')
def test_app():
    """Create a Flask application for testing."""
    app = create_app(testing=True)
    
    with app.app_context():
        db.create_all()

    ctx = app.app_context()
    ctx.push()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()

@pytest.fixture(scope='function')
def test_db(test_app):
    """Provide a database for the tests."""
    with test_app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()

@pytest.fixture(scope='function')
def client(test_app):
    """Provide a test client for the tests."""
    return test_app.test_client()

@pytest.fixture
def login_user_helper(client, test_db):
    """Helper to log in a user."""
    def _login(user):
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['_fresh'] = True
    return _login

@pytest.fixture
def user_with_programme(test_app, test_db):
    """Create a user with an associated programme."""
    with test_app.app_context():
        department = Department(nom="Département Informatique")
        test_db.session.add(department)
        test_db.session.commit()

        programme = Programme(nom="Programme Test", department_id=department.id)
        test_db.session.add(programme)
        test_db.session.commit()

        user = User(username="testuser", password="hashedpassword")
        test_db.session.add(user)
        test_db.session.commit()

        # Associate the user with the programme
        user.programmes.append(programme)
        test_db.session.commit()

        # Refresh the user to avoid DetachedInstanceError
        test_db.session.refresh(user)  
        return user  # Now, it's attached to the active session

@pytest.fixture
def user_without_programme(test_app, test_db):
    """Create a user without an associated programme."""
    with test_app.app_context():
        user = User(username="testuser2", password="hashedpassword")
        test_db.session.add(user)
        test_db.session.commit()

        # Refresh the user to avoid DetachedInstanceError
        test_db.session.refresh(user)
        return user

@pytest.fixture
def login_user(client, user_with_programme, test_db):
    """Simulate logging in a user with a programme."""
    with test_db.session.no_autoflush:
        user_with_programme = test_db.session.merge(user_with_programme)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_with_programme.id)

    return user_with_programme

@pytest.fixture
def login_user_without_programme(client, user_without_programme):
    """Simulate logging in a user without a programme."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_without_programme.id)  # Flask-Login stores the user ID in the session
    return user_without_programme
