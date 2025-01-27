import pytest
import sys, os
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))
os.environ['TESTING'] = 'True'

from main import create_app, db
from app.routes.cours import cours_bp
from app.routes.routes import main as main_bp
from app.routes.plan_de_cours import plan_de_cours_bp

from utils.auth import login_manager  # Importer login_manager

class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing
    SERVER_NAME = 'localhost.localdomain'
    APPLICATION_ROOT = '/'
    PREFERRED_URL_SCHEME = 'http'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test_key'

@pytest.fixture(scope='function')
def test_app():
    app = create_app()
    app.config.from_object(TestConfig)
    login_manager.init_app(app)
    app.register_blueprint(cours_bp)  # Explicitement enregistrer le blueprint
    app.register_blueprint(main_bp)
    app.register_blueprint(plan_de_cours_bp)
    db.init_app(app)
    return app

@pytest.fixture(scope='function')
def test_db(test_app):
    with test_app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()

@pytest.fixture(scope='function')
def client(test_app):
    return test_app.test_client()

@pytest.fixture
def login_user_helper(client, test_db):
    """Helper to log in a user."""
    def _login(user):
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['_fresh'] = True
    return _login