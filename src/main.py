from flask import Flask, session, jsonify
import tempfile
from flask_login import current_user
from flask_ckeditor import CKEditor
from dotenv import load_dotenv
import os
from utils.auth import login_manager
from app.routes.cours import cours_bp
from app.routes.chat import chat
from app.routes.programme import programme_bp
from app.routes import routes
from app.routes.system import system_bp
from app.routes.settings import settings_bp
from app.routes.evaluation import evaluation_bp
from app.routes.plan_cadre import plan_cadre_bp
from flask_wtf import CSRFProtect
from datetime import timedelta, datetime, timezone
from app.routes.plan_de_cours import plan_de_cours_bp
from app.models import db, Cours, BackupConfig
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from flask_migrate import Migrate
import atexit
from utils.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler, schedule_backup
import logging
from utils.db_tracking import init_change_tracking
from config.version import __version__ 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder="app/templates")

    # Vérifier si on est en mode test
    if os.environ.get('TESTING'):
        return app  # Retourner l'app sans configurer le backup


    worker_id = os.getenv('GUNICORN_WORKER_ID')
    is_primary_worker = worker_id == '0' or worker_id is None
     
    login_manager.init_app(app)
    
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['CKEDITOR_PKG_TYPE'] = 'standard'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    csrf = CSRFProtect(app)

    @app.context_processor
    def inject_version():
        return dict(version=__version__)

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


    @app.before_request
    def before_request():
        try:
            db.session.execute(text("SELECT 1"))
            db.session.commit()
            
            session.permanent = True
            now = datetime.now(timezone.utc)
            session['last_activity'] = now.isoformat()
        except SQLAlchemyError as e:
            logger.error(f"Database connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        session.permanent = True
        now = datetime.now(timezone.utc)
        
        last_activity_str = session.get('last_activity')
        if last_activity_str:
            try:
                last_activity = datetime.fromisoformat(last_activity_str)
            except ValueError:
                logout_user()
                return redirect(url_for('login'))

            elapsed = now - last_activity
            if elapsed > app.config['PERMANENT_SESSION_LIFETIME']:
                logout_user()
                return redirect(url_for('login'))

        session['last_activity'] = now.isoformat()

    @app.after_request
    def after_request(response):
        if current_user.is_authenticated and session.modified:
            session.modified = True
        return response

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



    BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # Get the base directory (src/)
    DB_DIR = os.path.join(BASE_DIR, "database")  # Define the database directory
    DB_PATH = os.path.join(DB_DIR, "programme.db")  # Define the database file path

    print(f"🔍 Debug: Database Path -> {DB_PATH}")  # Add this line to debug

    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}?timeout=30"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['DB_PATH'] = DB_PATH

    db.init_app(app)
    migrate = Migrate(app, db)
    ckeditor = CKEditor(app)
    init_change_tracking(db)

    with app.app_context():
        with db.engine.connect() as connection:
            connection.execute(text('PRAGMA journal_mode=WAL;'))
        
        if not scheduler.running and is_primary_worker:
            start_scheduler()
            
            with app.app_context():
                result = db.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
                )).fetchone()
                
                if result:  # La table existe, on peut planifier les sauvegardes
                    schedule_backup(app)
                else:
                    logger.warning("⚠️ Table 'backup_config' introuvable, planification des sauvegardes désactivée.")


    app.register_blueprint(routes.main)
    app.register_blueprint(settings_bp)
    app.register_blueprint(cours_bp)
    app.register_blueprint(programme_bp)
    app.register_blueprint(plan_cadre_bp)
    app.register_blueprint(plan_de_cours_bp)
    app.register_blueprint(chat)
    app.register_blueprint(system_bp)
    app.register_blueprint(evaluation_bp)

    @app.route('/version')
    def version():
        return jsonify(version=__version__)


    atexit.register(shutdown_scheduler)
    atexit.register(checkpoint_wal)

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)