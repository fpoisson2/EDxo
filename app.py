from flask import Flask, session
from flask_login import current_user
from flask_ckeditor import CKEditor
from dotenv import load_dotenv
import os
from utils import get_db_connection
from auth import login_manager
from routes.cours import cours_bp
from routes.chat import chat
from routes.programme import programme_bp
from routes import routes
from routes.settings import settings_bp
from routes.plan_cadre import plan_cadre_bp
from flask_wtf import CSRFProtect
from datetime import timedelta, datetime, timezone
from routes.plan_de_cours import plan_de_cours_bp
from models import db, Cours  # Import specific models
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import atexit


load_dotenv()

# Initialize Flask application
app = Flask(__name__)

login_manager.init_app(app)

print(os.path.abspath('programme.db'))

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  
app.config['SESSION_COOKIE_SECURE'] = True  # Use HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Mitigate CSRF
csrf = CSRFProtect(app)

def checkpoint_wal():
    with app.app_context():
        try:
            db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            db.session.commit()
            print("WAL checkpointed successfully.")
        except SQLAlchemyError as e:
            print(f"Error during WAL checkpoint: {e}")


@app.before_request
def before_request():
    try:
        # Test the database connection
        db.session.execute(text("SELECT 1"))
        db.session.commit()  # Commit to ensure the session is active
        print("Database connection successful")
        
        # Test retrieving a Cours record (first one in the database)
        cours = Cours.query.first()  # Or you can use .get() or other query methods
        if cours:
            print(f"Retrieved Cours: {cours.nom} (ID: {cours.id})")
        else:
            print("No Cours record found in the database.")
        
    except SQLAlchemyError as e:
        # Catch database-related errors
        print(f"Database connection failed: {e}")
    except Exception as e:
        # Catch any other unexpected errors
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

@app.after_request
def after_request(response):
    if current_user.is_authenticated:
        session.modified = True  # Optionally regenerate session ID
    return response

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.abspath('programme.db?timeout=30')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize db
db.init_app(app)

ckeditor = CKEditor(app)

with app.app_context():
    with db.engine.connect() as connection:
        connection.execute(text('PRAGMA journal_mode=WAL;'))


# Import and register routes
app.register_blueprint(routes.main)
app.register_blueprint(settings_bp)
app.register_blueprint(cours_bp)
app.register_blueprint(programme_bp)
app.register_blueprint(plan_cadre_bp)
app.register_blueprint(plan_de_cours_bp)
app.register_blueprint(chat)

# Register the checkpoint function to be called on exit
atexit.register(checkpoint_wal)

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
