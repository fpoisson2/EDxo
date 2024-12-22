from flask import Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from jinja2 import Template
from docxtpl import DocxTemplate
from io import BytesIO
import sqlite3
import json
import logging
import os
import markdown
import bleach
from bs4 import BeautifulSoup

from forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    MultiCheckboxField,
    PlanCadreForm,
    CapaciteForm,
    SavoirEtreForm,
    CompetenceDeveloppeeForm,
    ObjetCibleForm,
    CoursRelieForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm, 
    GenerationSettingForm
)
from utils import (
    get_db_connection,
    parse_html_to_list,
    parse_html_to_nested_list,
    get_plan_cadre_data,
    replace_tags_jinja2,
    process_ai_prompt
)
from models import User  # Import User from models.py
from constants import SECTIONS

# Initialize Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'votre_cle_secrete'
app.config['WTF_CSRF_ENABLED'] = True
app.config['CKEDITOR_PKG_TYPE'] = 'standard'

ckeditor = CKEditor(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("La clé API OpenAI n'est pas définie dans les variables d'environnement.")

# Configure Flask-Login
login_manager = LoginManager()
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM User WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['password'], user['role'])
    return None

@app.template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)

# Import and register routes
import routes
app.register_blueprint(routes.main)

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
