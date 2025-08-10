"""Application factory and setup for the EDxo project."""

import sys

# Ensure consistent module imports whether using ``app`` or ``src.app``
sys.modules.setdefault("app", sys.modules[__name__])

# src/app/__init__.py

# TODO: Ajouter un status au plan de cours (Brouillon, en révision, complété), Permettre l'édition seulement lorsqu'en brouillon pour le prof. Permettre l'édition lorsqu'il est en révision par le coordo.
# TODO: Ajouter un status au plan-cadre (adopté avec date d'adoption, en travail), ne pas permettre l'édition lorsqu'adopté à moins de le remettre en mode en travail, seulement le coordo et l'admin devrait pouvoir faire ça.
# TODO: Lorsque je surligne du texte dans le calendrier du plan de cours, ca déplace le bloque plutôt que de surligner le texte.
# TODO: La CP peut créer un plan de cours et peu générer une grille D'évaluation ce qui ne devrait pas être le cas
# TODO: Saisir plans de cours S1 (sauf 1J5=déja fait)
# TODO: Faudrait pouvoir mettre 2 ou 3 enseignants sur un plan de cours

from .models import BackupConfig

import atexit
import logging
import os
from datetime import timedelta, datetime, timezone
from pathlib import Path

from flask_session import Session


from dotenv import load_dotenv
from flask import Flask, session, jsonify, redirect, url_for, request, current_app
from flask_login import current_user, logout_user, UserMixin
from flask_migrate import Migrate
from sqlalchemy import text, UniqueConstraint
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

# Import models and routes
from . import models
from .routes import routes
from .routes.chat import chat
# Import blueprints
from .routes.cours import cours_bp
from .routes.evaluation import evaluation_bp
from .routes.gestion_programme import gestion_programme_bp
from .routes.plan_cadre import plan_cadre_bp
from .routes.plan_de_cours import plan_de_cours_bp
from .routes.programme import programme_bp
from .routes.settings import settings_bp
from .routes.system import system_bp
from .routes.ocr_routes import ocr_bp
from .routes.grilles import grille_bp

# Import version
from config.version import __version__
# Import centralized extensions
from src.extensions import db, login_manager, ckeditor, csrf, limiter, bcrypt
from utils.db_tracking import init_change_tracking
from utils.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler, schedule_backup

from werkzeug.security import generate_password_hash

from dotenv import load_dotenv 

from celery_app import celery, init_celery 

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Define TestConfig within the application code
class TestConfig:
    """Testing configuration."""
    TESTING = True
    SERVER_NAME = 'localhost.localdomain'
    APPLICATION_ROOT = '/'
    PREFERRED_URL_SCHEME = 'http'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test_key'
    RECAPTCHA_PUBLIC_KEY = 'test_public'
    RECAPTCHA_SECRET_KEY = 'test_secret'
    # Add other testing-specific configurations here


def create_app(testing=False):
    load_dotenv()
    print(f"--- DEBUG: SECRET_KEY lue depuis l'environnement: {os.getenv('SECRET_KEY')} ---")
    base_path = os.path.dirname(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=os.path.join(base_path, "static")
    )

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Configuration based on environment
    if testing:
        app.config.from_object(TestConfig)
    else:
        BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        DB_DIR = os.path.join(BASE_DIR, "database")
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
        DB_PATH = os.path.join(DB_DIR, "programme.db")

        print(f"🔍 Debug: Static folder -> {app.static_folder}")

        base_path = Path(__file__).parent.parent

        SESS_DIR = os.path.join(BASE_DIR, "flask_sessions")
        os.makedirs(SESS_DIR, exist_ok=True)      # ← avant Session(app)
        app.config.update(
            PREFERRED_URL_SCHEME='https',
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}?timeout=30",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DB_PATH=DB_PATH,
            UPLOAD_FOLDER=os.path.join(base_path, 'static', 'docs'),
            SECRET_KEY=os.getenv('SECRET_KEY'),
            RECAPTCHA_SITE_KEY=os.getenv('RECAPTCHA_PUBLIC_KEY'),
            RECAPTCHA_SECRET_KEY=os.getenv('RECAPTCHA_PRIVATE_KEY'),
            MISTRAL_API_KEY=os.getenv('MISTRAL_API_KEY'),
            OPENAI_API_KEY=os.getenv('OPENAI_API_KEY'),
            MISTRAL_MODEL_OCR="mistral-ocr-latest",
            OPENAI_MODEL_SECTION = "gpt-4.1", # Modèle pour la détection de section
            OPENAI_MODEL_EXTRACTION = "gpt-4.1-mini", # Modèle pour l'extraction de compétences
            DEFAULT_CHAT_MODEL=os.getenv('DEFAULT_CHAT_MODEL'),
            WTF_CSRF_ENABLED=True,
            CKEDITOR_PKG_TYPE='standard',
            PERMANENT_SESSION_LIFETIME=timedelta(days=30),
            SESSION_COOKIE_SECURE = False,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_TYPE='filesystem',
            SESSION_FILE_DIR=os.path.join(BASE_DIR, 'flask_sessions'),  # si filesystem
            SESSION_PERMANENT=False,
            CELERY_BROKER_URL='redis://127.0.0.1:6379/0',
            CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/0',
            TXT_OUTPUT_DIR=os.path.join(BASE_DIR, 'txt_outputs')
        )
        Session(app)

    app.config.setdefault('DEFAULT_CHAT_MODEL', os.getenv('DEFAULT_CHAT_MODEL'))
    # Jinja filter to compute perceived brightness of a hex color
    def brightness(hex_color):
        if not hex_color:
            return 0
        s = hex_color.lstrip('#')
        if len(s) != 6:
            return 0
        try:
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
        except ValueError:
            return 0
        # Perceived brightness formula
        return (r * 299 + g * 587 + b * 114) / 1000
    app.jinja_env.filters['brightness'] = brightness

    # Initialize extensions
    login_manager.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)

    from .models import User  # Import your User model

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # Optional but recommended: Set the login view
    login_manager.login_view = 'main.login'
    login_manager.login_message_category = 'info'

    db.init_app(app)
    ckeditor.init_app(app)
    csrf.init_app(app)
    init_change_tracking(db)

    if not testing:
        migrate = Migrate(app, db)
        worker_id = os.getenv('GUNICORN_WORKER_ID')
        is_primary_worker = worker_id == '0' or worker_id is None

    init_celery(app)

    # Register blueprints

    app.register_blueprint(routes.main)
    app.register_blueprint(settings_bp)
    app.register_blueprint(cours_bp)
    app.register_blueprint(programme_bp)
    app.register_blueprint(plan_cadre_bp)
    app.register_blueprint(plan_de_cours_bp)
    app.register_blueprint(chat)
    app.register_blueprint(system_bp)
    app.register_blueprint(evaluation_bp)
    app.register_blueprint(gestion_programme_bp)
    app.register_blueprint(ocr_bp)
    app.register_blueprint(grille_bp)

    # Register helpers and handlers
    @app.context_processor
    def inject_version():
        return dict(version=__version__)

    @app.before_request
    def before_request():
        # Define endpoints that do not require authentication
        PUBLIC_ENDPOINTS = {
            'static',
            'main.login',
            'main.get_credit_balance',
            'version',
            'main.forgot_password',
            'main.reset_password'
        }

        if request.endpoint in PUBLIC_ENDPOINTS or request.path.startswith('/static/'):
            return

        if not current_user.is_authenticated:
            logger.warning(f"🔄 User NOT authenticated! Redirecting {request.path} to /login")
            return redirect(url_for('main.login', next=request.path))

        try:
            # Verify database connection
            db.session.execute(text("SELECT 1"))
            db.session.commit()

            # Manage session expiration
            session.permanent = True
            now = datetime.now(timezone.utc)
            last_activity_str = session.get('last_activity')
            if last_activity_str:
                try:
                    last_activity = datetime.fromisoformat(last_activity_str)
                    elapsed = now - last_activity
                    if elapsed > app.config['PERMANENT_SESSION_LIFETIME']:
                        logger.info("🔄 Session expired. Logging out user.")
                        logout_user()
                        session.clear()
                        return redirect(url_for('main.login'))
                except (ValueError, TypeError):
                    session['last_activity'] = now.isoformat()
            session['last_activity'] = now.isoformat()

            # Update 'last_login' at most once per minute
            if (not current_user.last_login or
                    (datetime.utcnow() - current_user.last_login).total_seconds() > 60):
                current_user.last_login = datetime.utcnow()
                db.session.commit()

        except SQLAlchemyError as e:
            logger.error(f"❌ Database error: {e}")
            return "Database Error", 500
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return "Server Error", 500

    @app.after_request
    def after_request(response):
        if current_user.is_authenticated and session.modified:
            session.modified = True
        return response

    @app.route('/version')
    def version():
        return jsonify(version=__version__)

    def checkpoint_wal():
        with app.app_context():
            try:
                # Check if the backup_config table exists before accessing it
                result = db.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
                )).fetchone()
                if result:  # Table exists
                    config = BackupConfig.query.first()
                    if config and config.enabled:
                        try:
                            schedule_backup(app)
                        except Exception as e:
                            logger.error(f"Erreur lors de la planification des sauvegardes: {e}")
                else:
                    logger.warning(
                        "⚠️ Table 'backup_config' introuvable, la planification des sauvegardes est ignorée.")

                from .init.prompt_settings import init_plan_de_cours_prompts
                init_plan_de_cours_prompts()

                # Perform WAL checkpoint
                db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
                db.session.commit()
                logger.info("✅ WAL checkpointed successfully.")
            except SQLAlchemyError as e:
                logger.error(f"❌ Erreur lors du checkpoint WAL : {e}")
            except Exception as e:
                logger.error(f"❌ Erreur inattendue : {e}")

    if not testing:
        # Production-only setup
        # Only start the scheduler if NOT running in a Celery worker
        if not os.environ.get("CELERY_WORKER"):
            with app.app_context():
                # Set WAL journal mode
                with db.engine.connect() as connection:
                    connection.execute(text('PRAGMA journal_mode=WAL;'))

                # Determine if this is the primary worker
                worker_id = os.getenv('GUNICORN_WORKER_ID')
                is_primary_worker = worker_id == '0' or worker_id is None

                if not scheduler.running and is_primary_worker:
                    start_scheduler()
                    result = db.session.execute(text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
                    )).fetchone()

                    if result:
                        schedule_backup(app)
                    else:
                        logger.warning(
                            "⚠️ Table 'backup_config' introuvable, planification des sauvegardes est désactivée.")

            # Register atexit handlers for graceful shutdown and checkpointing
            atexit.register(shutdown_scheduler)
            atexit.register(checkpoint_wal)
        else:
            logger.info("Celery worker detected; skipping scheduler startup and related atexit handlers.")

    # ---------------------------------------------------
    # Database initialization: Create DB and admin user
    # ---------------------------------------------------
    if not testing:
        with app.app_context():
            # Always create missing tables; create_all() will do nothing if tables already exist.
            db.create_all()
            from .models import User  # Ensure the User model is imported

            # Check if an admin user exists; if not, create one.
            if not User.query.filter_by(role='admin').first():
                hashed_password = generate_password_hash('admin1234', method='scrypt') #add
                admin_user = User(username='admin', password=hashed_password, role='admin')
                db.session.add(admin_user)
                db.session.commit()
                logger.info("Admin user created with username 'admin' and default password 'admin'.")
                logger.info("Please change the default password immediately after first login.")
            else:
                logger.info("Admin user already exists.")
    return app
