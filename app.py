from flask import Flask
from flask_ckeditor import CKEditor
from dotenv import load_dotenv
import os
from utils import get_db_connection
from auth import login_manager
from routes import routes
from routes.settings import settings_bp
from routes.plan_cadre import plan_cadre_bp

# Initialize Flask application
app = Flask(__name__)

login_manager.init_app(app)

app.config['SECRET_KEY'] = 'votre_cle_secrete' #je devrais changer ca
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'

ckeditor = CKEditor(app)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("La clé API OpenAI n'est pas définie dans les variables d'environnement.")

# Import and register routes
app.register_blueprint(routes.main)
app.register_blueprint(settings_bp)
app.register_blueprint(plan_cadre_bp)

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
