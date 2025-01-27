import pytest
import sys, os
from pathlib import Path
from flask_wtf.csrf import CSRFProtect  # Add this import
sys.path.append(str(Path(__file__).parent.parent / 'src'))
os.environ['TESTING'] = 'True'
from main import create_app, db
from app.routes.cours import cours_bp
from app.routes.routes import main as main_bp
from app.routes.plan_de_cours import plan_de_cours_bp
from app.routes.programme import programme_bp
from utils.auth import login_manager  # Importer login_manager
from flask_login import current_user
from app.models import User, Programme, Department

class TestConfig:
    TESTING = True
    
    SERVER_NAME = 'localhost.localdomain'
    APPLICATION_ROOT = '/'
    PREFERRED_URL_SCHEME = 'http'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test_key'

@pytest.fixture(scope='function')
def test_app():
    """Créer une application Flask pour les tests."""
    app = create_app()
    app.config.from_object(TestConfig)
    login_manager.init_app(app)
    csrf = CSRFProtect(app)
    csrf.init_app(app)  # Initialisation CSRF

    app.register_blueprint(cours_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(plan_de_cours_bp)
    app.register_blueprint(programme_bp)

    with app.app_context():
        db.init_app(app)
        db.create_all()  # 🔴 Assure que toutes les tables sont créées avant les tests

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

@pytest.fixture
def user_with_programme(test_app, test_db):
    """Créer un utilisateur avec un programme associé."""
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

        # Associer l'utilisateur au programme
        user.programmes.append(programme)
        test_db.session.commit()

        # Rafraîchir l'utilisateur pour éviter DetachedInstanceError
        test_db.session.refresh(user)  
        return user  # Maintenant, il reste attaché à la session active

@pytest.fixture
def user_without_programme(test_app, test_db):
    """Créer un utilisateur sans programme associé."""
    with test_app.app_context():
        user = User(username="testuser2", password="hashedpassword")
        test_db.session.add(user)
        test_db.session.commit()

        # Rafraîchir l'utilisateur pour éviter DetachedInstanceError
        test_db.session.refresh(user)
        return user


@pytest.fixture
def login_user(client, user_with_programme, test_db):
    """Simuler l'authentification de l'utilisateur avec programme."""
    with test_db.session.no_autoflush:
        user_with_programme = test_db.session.merge(user_with_programme)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_with_programme.id)

    return user_with_programme

@pytest.fixture
def login_user_without_programme(client, user_without_programme):
    """Simuler l'authentification de l'utilisateur sans programme."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_without_programme.id)  # Flask-Login stocke l'ID utilisateur dans la session
    return user_without_programme