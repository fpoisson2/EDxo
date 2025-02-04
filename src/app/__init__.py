# src/app/__init__.py

import os
import logging
from pathlib import Path
from datetime import timedelta, datetime, timezone
from dotenv import load_dotenv

from flask import Flask, session, jsonify, redirect, url_for, request
from flask_login import current_user, logout_user
from flask_ckeditor import CKEditor  # Remove this if using centralized CKEditor
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import atexit

# Import centralized extensions
from extensions import db, login_manager, ckeditor, csrf, limiter, bcrypt
from utils.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler, schedule_backup
from utils.db_tracking import init_change_tracking

# Import version
from config.version import __version__

# Import blueprints
from app.routes.cours import cours_bp
from app.routes.chat import chat
from app.routes.programme import programme_bp
from app.routes.system import system_bp
from app.routes.settings import settings_bp
from app.routes.evaluation import evaluation_bp
from app.routes.plan_cadre import plan_cadre_bp
from app.routes.plan_de_cours import plan_de_cours_bp
from app.routes import routes
from app.routes.gestion_programme import gestion_programme_bp

from flask_bcrypt import Bcrypt

# Import models
from app.models import BackupConfig

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
    # Add other testing-specific configurations here

def create_app(testing=False):
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
        DB_PATH = os.path.join(DB_DIR, "programme.db")  
        
        print(f"🔍 Debug: Static folder -> {app.static_folder}")
        
        base_path = Path(__file__).parent.parent
        app.config.update(
            PREFERRED_URL_SCHEME='https',
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}?timeout=30",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DB_PATH=DB_PATH,
            UPLOAD_FOLDER=os.path.join(base_path, 'static', 'docs'),
            SECRET_KEY=os.getenv('SECRET_KEY'),
            WTF_CSRF_ENABLED=True,
            CKEDITOR_PKG_TYPE='standard',
            PERMANENT_SESSION_LIFETIME=timedelta(days=30),
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_TYPE='filesystem',
            CELERY_BROKER_URL='amqp://guest:guest@localhost//',
            CELERY_RESULT_BACKEND='rpc://'  # or another backend of your choice
        )

    # Initialize extensions
    login_manager.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)

    from app.models import User  # Import your User model

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except:
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

    # Register blueprints (both testing and production)
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

    # Register helpers and handlers
    @app.context_processor
    def inject_version():
        return dict(version=__version__)
        
    @app.before_request
    def before_request():
        # Définir les endpoints publics qui ne nécessitent pas d'authentification
        PUBLIC_ENDPOINTS = {
            'static', 
            'main.login', 
            'main.logout', 
            'main.get_credit_balance',
            'version'
        }
        
        if request.endpoint in PUBLIC_ENDPOINTS or request.path.startswith('/static/'):
            return

        if not current_user.is_authenticated:
            logger.warning(f"🔄 User NOT authenticated! Redirecting {request.path} to /login")
            return redirect(url_for('main.login', next=request.path))

        try:
            # Vérifier la connexion à la BDD
            db.session.execute(text("SELECT 1"))
            db.session.commit()

            # Gestion de l'expiration de la session
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

            # ────────────────────────────────────────────────────────────────
            # Mise à jour de 'last_login' pour refléter la dernière activité de l'utilisateur
            # Ici, nous mettons à jour le champ au moins une fois par minute pour éviter trop d'écritures.
            if (not current_user.last_login or 
                (datetime.utcnow() - current_user.last_login).total_seconds() > 60):
                current_user.last_login = datetime.utcnow()
                db.session.commit()
            # ────────────────────────────────────────────────────────────────

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
                # Vérifier si la table backup_config existe avant d'y accéder
                result = db.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
                )).fetchone()
                if result:  # La table existe
                    config = BackupConfig.query.first()
                    if config and config.enabled:
                        try:
                            schedule_backup(app)
                        except Exception as e:
                            logger.error(f"Erreur lors de la planification des sauvegardes: {e}")
                else:
                    logger.warning("⚠️ Table 'backup_config' introuvable, la planification des sauvegardes est ignorée.")
                    
                from app.init.prompt_settings import init_plan_de_cours_prompts
                init_plan_de_cours_prompts()
                
                # Effectuer un checkpoint WAL
                db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
                db.session.commit()
                logger.info("✅ WAL checkpointed successfully.")
            except SQLAlchemyError as e:
                logger.error(f"❌ Erreur lors du checkpoint WAL : {e}")
            except Exception as e:
                logger.error(f"❌ Erreur inattendue : {e}")

    if not testing:
        # Production-only setup
        with app.app_context():
            # Set WAL journal mode
            with db.engine.connect() as connection:
                connection.execute(text('PRAGMA journal_mode=WAL;'))
            
            if not scheduler.running and is_primary_worker:
                start_scheduler()
                result = db.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
                )).fetchone()
                
                if result:
                    schedule_backup(app)
                else:
                    logger.warning("⚠️ Table 'backup_config' introuvable, planification des sauvegardes est désactivée.")

        # Register atexit handlers
        atexit.register(shutdown_scheduler)
        atexit.register(checkpoint_wal)

    return app
