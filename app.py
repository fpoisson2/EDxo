from flask import Flask, session
from flask_login import current_user
from flask_ckeditor import CKEditor
from dotenv import load_dotenv
import os
from utils import get_db_connection
from auth import login_manager
from routes.cours import cours_bp
from routes.programme import programme_bp
from routes import routes
from routes.settings import settings_bp
from routes.plan_cadre import plan_cadre_bp
from flask_wtf import CSRFProtect
from datetime import timedelta, datetime, timezone

load_dotenv()

# Initialize Flask application
app = Flask(__name__)

login_manager.init_app(app)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  
app.config['SESSION_COOKIE_SECURE'] = True  # Use HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Mitigate CSRF
csrf = CSRFProtect(app)

@app.before_request
def before_request():
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

# Import and register routes
app.register_blueprint(routes.main)
app.register_blueprint(settings_bp)
app.register_blueprint(cours_bp)
app.register_blueprint(programme_bp)
app.register_blueprint(plan_cadre_bp)

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
