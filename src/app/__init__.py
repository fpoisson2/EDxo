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
import os
from datetime import timedelta, datetime, timezone
from pathlib import Path

from flask_session import Session
from cachelib import FileSystemCache

from flask import Flask, session, jsonify, redirect, url_for, request, current_app
from flask_login import current_user, logout_user, UserMixin
from flask_migrate import Migrate
from sqlalchemy import text, UniqueConstraint
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

# Import models and routes
from . import models
from .routes import routes
# Import route modules that extend the 'main' blueprint
from .routes import admin_cegeps  # noqa: F401
from .routes import admin_programmes  # noqa: F401
from .routes import programmes_cegep  # noqa: F401
from .routes import admin_users  # noqa: F401
from .routes import courses_management  # noqa: F401
from .routes import competences_management  # noqa: F401
from .routes import fil_conducteur_routes  # noqa: F401
from .routes import settings_departements  # noqa: F401
from .routes import admin_docx_schema  # noqa: F401
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
from .routes.api import api_bp
from .routes.oauth import oauth_bp
from .routes.tasks import tasks_bp

# Import version
from ..config.version import __version__
# Import centralized extensions
from ..extensions import db, login_manager, ckeditor, csrf, limiter, bcrypt
from flask_wtf.csrf import generate_csrf
from ..utils.db_tracking import init_change_tracking
from ..utils.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler, schedule_backup

from werkzeug.security import generate_password_hash

from ..celery_app import celery, init_celery
from ..config.env import (
    SECRET_KEY,
    RECAPTCHA_PUBLIC_KEY,
    RECAPTCHA_PRIVATE_KEY,
    OPENAI_API_KEY,
    OPENAI_MODEL_SECTION,
    OPENAI_MODEL_EXTRACTION,
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    GUNICORN_WORKER_ID,
    CELERY_WORKER,
    validate,
)

from ..utils.logging_config import get_logger

# Initialize logger
logger = get_logger(__name__)


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
    # Avoid Flask-Limiter warning by explicitly setting storage backend in tests
    RATELIMIT_STORAGE_URI = 'memory://'
    # Add other testing-specific configurations here


def create_app(testing=False):
    if not testing:
        validate()
        if SECRET_KEY:
            logger.debug("SECRET_KEY environment variable is set.")
        else:
            logger.warning("SECRET_KEY environment variable is not set.")
    base_path = os.path.dirname(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=os.path.join(base_path, "static")
    )

    # Enable response compression for text assets if Flask-Compress is available
    try:
        from flask_compress import Compress
        app.config.setdefault('COMPRESS_ALGORITHM', 'br,gzip')
        app.config.setdefault('COMPRESS_LEVEL', 6)
        app.config.setdefault('COMPRESS_BR_LEVEL', 5)
        app.config.setdefault('COMPRESS_MIMETYPES', [
            'text/html', 'text/css', 'text/xml', 'text/plain',
            'application/javascript', 'application/x-javascript', 'application/json',
            'image/svg+xml'
        ])
        Compress(app)
        logger.info("Compression enabled (Flask-Compress)")
    except Exception as e:
        logger.info(f"Compression not enabled: {e}")

    # Respect reverse proxy headers for scheme, host and path prefix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    # Configuration based on environment
    if testing:
        app.config.from_object(TestConfig)
    else:
        BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        DB_DIR = os.path.join(BASE_DIR, "database")
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
        DB_PATH = os.path.join(DB_DIR, "programme.db")

        # Static folder resolved via app.static_folder

        base_path = Path(__file__).parent.parent

        SESS_DIR = os.path.join(BASE_DIR, "flask_sessions")
        os.makedirs(SESS_DIR, exist_ok=True)      # ensure dir exists for FileSystemCache
        # Shared upload directory (bind-mounted volume recommended)
        UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        app.config.update(
            PREFERRED_URL_SCHEME='https',
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}?timeout=30",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DB_PATH=DB_PATH,
            UPLOAD_FOLDER=UPLOAD_DIR,
            SECRET_KEY=SECRET_KEY,
            RECAPTCHA_SITE_KEY=RECAPTCHA_PUBLIC_KEY,
            RECAPTCHA_SECRET_KEY=RECAPTCHA_PRIVATE_KEY,
            OPENAI_API_KEY=OPENAI_API_KEY,
            # Forcer l'utilisation de gpt-5 partout, ignorer les variables d'environnement
            OPENAI_MODEL_SECTION='gpt-5',
            OPENAI_MODEL_EXTRACTION='gpt-5',
            WTF_CSRF_ENABLED=True,
            SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=30),
            # Prefer CDN for Toast UI assets by default; set TOASTUI_USE_CDN=0 to self-host
            TOASTUI_USE_CDN=(os.getenv('TOASTUI_USE_CDN', '1') == '1'),
            TOASTUI_CDN_PROVIDER=os.getenv('TOASTUI_CDN_PROVIDER', 'jsdelivr'),  # 'toast' | 'jsdelivr'
            TOASTUI_VERSION=os.getenv('TOASTUI_VERSION', '3.2.2'),
            # EasyMDE (Markdown editor) config
            EASYMDE_USE_CDN=(os.getenv('EASYMDE_USE_CDN', '1') == '1'),
            EASYMDE_VERSION=os.getenv('EASYMDE_VERSION', '2.18.0'),
            # Asset hosting switches
            USE_LOCAL_BOOTSTRAP=(os.getenv('USE_LOCAL_BOOTSTRAP', '0') == '1'),
            USE_LOCAL_ICONS=(os.getenv('USE_LOCAL_ICONS', '0') == '1'),
            CKEDITOR_PKG_TYPE='standard',
            PERMANENT_SESSION_LIFETIME=timedelta(days=30),
            SESSION_COOKIE_SECURE = False,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            # Use CacheLib backend to avoid Flask-Session deprecation warnings
            SESSION_TYPE='cachelib',
            SESSION_CACHELIB=FileSystemCache(SESS_DIR, threshold=500, mode=0o700),
            SESSION_PERMANENT=False,
            # Configure limiter storage explicitly to avoid in-memory warning; override via env
            RATELIMIT_STORAGE_URI=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
            CELERY_BROKER_URL=CELERY_BROKER_URL,
            CELERY_RESULT_BACKEND=CELERY_RESULT_BACKEND,
            TXT_OUTPUT_DIR=os.path.join(BASE_DIR, 'txt_outputs')
        )
        Session(app)

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
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # Optional but recommended: Set the login view
    login_manager.login_view = 'main.login'
    login_manager.login_message_category = 'info'

    db.init_app(app)
    ckeditor.init_app(app)
    csrf.init_app(app)
    app.config.setdefault("WTF_CSRF_CHECK_DEFAULT", True)
    app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)
    init_change_tracking(db)

    # Bind Flask app to MCP server for OAuth verification
    from ..mcp_server.server import init_app as init_mcp_server
    init_mcp_server(app)

    if not testing:
        migrate = Migrate(app, db)
        worker_id = GUNICORN_WORKER_ID
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
    app.register_blueprint(api_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(tasks_bp)

    # Register helpers and handlers
    @app.context_processor
    def inject_version():
        return dict(version=__version__)

    @app.context_processor
    def inject_template_helpers():
        # Helper accessible dans les templates: has_endpoint('blueprint.endpoint')
        def has_endpoint(name: str) -> bool:
            try:
                return name in current_app.view_functions
            except Exception:
                return False
        # Cache-busting helper: build static URL with file mtime as version
        def asset_url(path: str) -> str:
            try:
                full_path = os.path.join(app.static_folder or "", path)
                ver = int(os.path.getmtime(full_path)) if os.path.exists(full_path) else int(datetime.now(timezone.utc).timestamp())
            except Exception:
                ver = int(datetime.now(timezone.utc).timestamp())
            return url_for('static', filename=path, v=ver)
        # Expose csrf_token() helper globally for templates
        return dict(has_endpoint=has_endpoint, asset_url=asset_url, csrf_token=generate_csrf)

    @app.context_processor
    def inject_docx_schema_pages():
        try:
            from .models import DocxSchemaPage
            pages = DocxSchemaPage.query.order_by(DocxSchemaPage.created_at.asc()).all()
        except Exception:
            pages = []
        return dict(docx_schema_pages=pages)

    @app.before_request
    def before_request():
        # Allow static files and explicitly public routes to bypass auth redirect
        view_func = app.view_functions.get(request.endpoint)
        if (
            request.endpoint == 'static' or
            request.path.startswith('/static/') or
            request.path.startswith('/api/') or
            request.path.startswith('/sse/') or  # MCP SSE endpoint is public (uses Bearer token)
            request.path in ('/token', '/register') or
            request.path.startswith('/.well-known/') or
            (view_func is not None and getattr(view_func, 'is_public', False))
        ):
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
            if not current_user.last_login:
                current_user.last_login = datetime.now(timezone.utc)
                db.session.commit()
            else:
                try:
                    last_login = current_user.last_login
                    # Ensure timezone-aware comparison
                    if getattr(last_login, 'tzinfo', None) is None:
                        last_login = last_login.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - last_login).total_seconds() > 60:
                        current_user.last_login = datetime.now(timezone.utc)
                        db.session.commit()
                except Exception:
                    # Fallback: set last_login safely
                    current_user.last_login = datetime.now(timezone.utc)
                    db.session.commit()

        except SQLAlchemyError as e:
            logger.error(f"❌ Database error: {e}")
            return "Database Error", 500
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return "Server Error", 500

    @app.after_request
    def after_request(response):
        if response.status_code == 401:
            response.headers[
                'WWW-Authenticate'
            ] = (
                f'Bearer resource_metadata="{request.url_root.rstrip('/')}/.well-known/oauth-protected-resource"'
            )
        if current_user.is_authenticated and session.modified:
            session.modified = True
        # Ensure CSRF token is generated and available to JS via cookie
        try:
            token = generate_csrf()
            response.set_cookie('csrf_token', token, samesite='Lax', secure=False, httponly=False)
        except Exception:
            pass
        return response

    # '/version' is now served by the main blueprint

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
        if not CELERY_WORKER:
            with app.app_context():
                # Set WAL journal mode
                with db.engine.connect() as connection:
                    connection.execute(text('PRAGMA journal_mode=WAL;'))

                # Determine if this is the primary worker
                worker_id = GUNICORN_WORKER_ID
                is_primary_worker = worker_id == '0' or worker_id is None

                # On primary worker startup, purge Celery queues and cleanup lingering task states
                def perform_celery_cleanup(tag: str = "startup"):
                    try:
                        logger.info(f"🧹 Celery cleanup ({tag}) – purge queues, revoke in-flight, clear results…")
                        # 1) Purge broker queues (queued tasks)
                        try:
                            purged = celery.control.purge()
                            logger.info(f"Celery purge: removed {purged} queued messages.")
                        except Exception as e:
                            logger.warning(f"Celery queue purge failed: {e}")

                        # 2) Revoke any active/reserved/scheduled tasks (best-effort)
                        try:
                            insp = celery.control.inspect(timeout=1.0)
                            ids = set()
                            active = (insp.active() or {}) if insp else {}
                            for w, tasks in (active or {}).items():
                                for t in tasks or []:
                                    tid = None
                                    if isinstance(t, dict):
                                        tid = t.get('id') or (t.get('request') or {}).get('id')
                                        if not tid and 'request' in t and hasattr(t['request'], 'id'):
                                            tid = getattr(t['request'], 'id', None)
                                    if tid:
                                        ids.add(tid)
                            reserved = (insp.reserved() or {}) if insp else {}
                            for w, tasks in (reserved or {}).items():
                                for t in tasks or []:
                                    tid = None
                                    if isinstance(t, dict):
                                        tid = t.get('id') or (t.get('request') or {}).get('id')
                                        if not tid and 'request' in t and hasattr(t['request'], 'id'):
                                            tid = getattr(t['request'], 'id', None)
                                    if tid:
                                        ids.add(tid)
                            scheduled = (insp.scheduled() or {}) if insp else {}
                            for w, tasks in (scheduled or {}).items():
                                for t in tasks or []:
                                    req = t.get('request') if isinstance(t, dict) else None
                                    tid = (req or {}).get('id') if req else (t.get('id') if isinstance(t, dict) else None)
                                    if tid:
                                        ids.add(tid)
                            for tid in ids:
                                try:
                                    celery.control.revoke(tid, terminate=True, signal="SIGTERM")
                                except Exception:
                                    pass
                            if ids:
                                logger.info(f"Revoked {len(ids)} in-flight tasks: {', '.join(list(ids)[:5])}{'…' if len(ids)>5 else ''}")
                        except Exception as e:
                            logger.warning(f"Celery revoke/inspect failed: {e}")

                        # 3) Clear Celery result backend keys and our cancel flags in Redis
                        try:
                            import redis
                            backend_url = celery.conf.result_backend
                            r = redis.Redis.from_url(backend_url)
                            deleted = 0
                            for pattern in ['celery-task-meta-*', 'celery-task-set-meta*', 'celery-group-meta*', 'celery-task-cache*', 'edxo:cancel:*']:
                                for key in r.scan_iter(match=pattern, count=1000):
                                    r.delete(key); deleted += 1
                            logger.info(f"Cleared {deleted} result/flag keys in Redis backend.")
                        except Exception as e:
                            logger.warning(f"Redis backend cleanup skipped/failed: {e}")

                        # 4) Clear residual broker-side Redis keys (unacked, pidbox, stray queues)
                        try:
                            import redis
                            broker_url = celery.conf.broker_url
                            rb = redis.Redis.from_url(broker_url)
                            bdel = 0
                            # Target only Celery-related broker keys; safe in dev/startup
                            for pattern in [
                                'celery',               # default queue list
                                'celery.*',
                                'unacked', 'unacked*',  # redis transport bookkeeping
                                'pidbox', 'celery.pidbox*',
                            ]:
                                for key in rb.scan_iter(match=pattern, count=1000):
                                    rb.delete(key); bdel += 1
                            if bdel:
                                logger.info(f"Cleared {bdel} broker-side Redis keys (queues/unacked/pidbox).")
                        except Exception as e:
                            logger.warning(f"Redis broker cleanup skipped/failed: {e}")
                    except Exception as e:
                        logger.warning(f"Celery cleanup ({tag}) encountered an issue: {e}")

                if is_primary_worker:
                    perform_celery_cleanup(tag="startup")

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

            # After scheduler starts, schedule a couple of delayed cleanup retries
            try:
                if is_primary_worker and scheduler.running:
                    now = datetime.now(timezone.utc)
                    # Retry shortly after startup to catch workers that connected later
                    scheduler.add_job(lambda: perform_celery_cleanup(tag="retry+5s"), 'date', run_date=now + timedelta(seconds=5), id='celery_cleanup_retry_1', replace_existing=True)
                    scheduler.add_job(lambda: perform_celery_cleanup(tag="retry+15s"), 'date', run_date=now + timedelta(seconds=15), id='celery_cleanup_retry_2', replace_existing=True)
            except Exception as e:
                logger.warning(f"Unable to schedule delayed Celery cleanup retries: {e}")

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

            try:
                # Check if an admin user exists; if not, create one.
                admin_user = User.query.filter_by(role='admin').first()
            except SQLAlchemyError as err:
                db.session.rollback()
                logger.warning(
                    "Skipping admin user creation due to database schema mismatch: %s", err
                )
            else:
                if not admin_user:
                    hashed_password = generate_password_hash('admin1234', method='scrypt')
                    admin_user = User(
                        username='admin',
                        password=hashed_password,
                        role='admin',
                    )
                    db.session.add(admin_user)
                    db.session.commit()
                    logger.info(
                        "Admin user created with username 'admin' and default password 'admin'."
                    )
                    logger.info(
                        "Please change the default password immediately after first login."
                    )
                else:
                    logger.info("Admin user already exists.")
    return app
