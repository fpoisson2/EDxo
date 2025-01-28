from flask_login import LoginManager
from flask import current_app
from app.models import User, db

login_manager = LoginManager()
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_view = 'main.login'

@login_manager.user_loader
def load_user(user_id):
    """
    Fonction Flask-Login pour charger l'utilisateur par son ID.
    Utilise la nouvelle méthode Session.get() de SQLAlchemy 2.0.
    """
    return db.session.get(User, int(user_id))