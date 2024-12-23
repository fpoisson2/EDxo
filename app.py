from flask import Flask
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


# Initialize Flask application
app = Flask(__name__)

login_manager.init_app(app)

app.config['SECRET_KEY'] = 'votre_cle_secrete' #je devrais changer ca
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'
csrf = CSRFProtect(app)

ckeditor = CKEditor(app)

# Import and register routes
app.register_blueprint(routes.main)
app.register_blueprint(settings_bp)
app.register_blueprint(cours_bp)
app.register_blueprint(programme_bp)
app.register_blueprint(plan_cadre_bp)

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
