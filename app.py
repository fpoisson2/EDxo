from flask import Flask, session
import tempfile
from flask_login import current_user
from flask_ckeditor import CKEditor
from dotenv import load_dotenv
import os
from utils import get_db_connection, schedule_backup
from auth import login_manager
from routes.cours import cours_bp
from routes.chat import chat
from routes.programme import programme_bp
from routes import routes
from routes.system import system_bp
from routes.settings import settings_bp
from routes.plan_cadre import plan_cadre_bp
from flask_wtf import CSRFProtect
from datetime import timedelta, datetime, timezone
from routes.plan_de_cours import plan_de_cours_bp
from models import db, Cours, BackupConfig  # Import specific models
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from flask_migrate import Migrate
import atexit
from utilitaires.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler

import logging

# Configuration de base du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()



# Initialize Flask application
app = Flask(__name__)

login_manager.init_app(app)

#print(os.path.abspath('programme.db'))

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  
app.config['SESSION_COOKIE_SECURE'] = True  # Use HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'  # Mitigate CSRF
csrf = CSRFProtect(app)

def checkpoint_wal():
    with app.app_context():
        config = BackupConfig.query.first()
        if config and config.enabled:
            try:
                schedule_backup(app)
            except Exception as e:
                logger.error(f"Erreur lors de la planification des sauvegardes: {e}")
        try:
            db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            db.session.commit()
            logger.info("WAL checkpointed successfully.")
        except SQLAlchemyError as e:
            logger.error(f"Error during WAL checkpoint: {e}")


@app.before_request
def before_request():
    try:
        # Test the database connection
        db.session.execute(text("SELECT 1"))
        db.session.commit()

        session.permanent = True
        now = datetime.now(timezone.utc)
        session['last_activity'] = now.isoformat()
        
    except SQLAlchemyError as e:
        print(f"Database connection failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")



    session.permanent = True
    now = datetime.now(timezone.utc)  # Offset-aware UTC time

    last_activity_str = session.get('last_activity')
    if last_activity_str:
        try:
            last_activity = datetime.fromisoformat(last_activity_str)
        except ValueError:
            # If parsing fails, log out the user for safety
            logout_user()
            return redirect(url_for('login'))

        elapsed = now - last_activity
        if elapsed > app.config['PERMANENT_SESSION_LIFETIME']:
            logout_user()
            return redirect(url_for('login'))

    # Update last_activity to current time in ISO format
    session['last_activity'] = now.isoformat()

def init_app():
    with app.app_context():
        if not scheduler.running:
            start_scheduler()
            schedule_backup(app)

@app.after_request
def after_request(response):
    if current_user.is_authenticated and session.modified:
        session.modified = True  # Optionally regenerate session ID
    return response

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.abspath('programme.db?timeout=30')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize db
db.init_app(app)

migrate = Migrate(app, db)

ckeditor = CKEditor(app)

with app.app_context():
    with db.engine.connect() as connection:
        connection.execute(text('PRAGMA journal_mode=WAL;'))

app.config['DB_PATH'] = os.path.abspath('programme.db')  # Add this after the other app.config settings

# Import and register routes
app.register_blueprint(routes.main)
app.register_blueprint(settings_bp)
app.register_blueprint(cours_bp)
app.register_blueprint(programme_bp)
app.register_blueprint(plan_cadre_bp)
app.register_blueprint(plan_de_cours_bp)
app.register_blueprint(chat)
app.register_blueprint(system_bp)

# Run the application
if __name__ == '__main__':
    init_app()
    atexit.register(shutdown_scheduler)
    atexit.register(checkpoint_wal)
    app.run(host='0.0.0.0', port=5000, debug=True)