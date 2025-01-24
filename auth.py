from flask_login import LoginManager
from models import db, User

# Configure Flask-Login
login_manager = LoginManager()
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_view = 'main.login'

@login_manager.user_loader
def load_user(user_id):
    """
    Fonction Flask-Login pour charger l'utilisateur par son ID.
    Utilise SQLAlchemy au lieu d'une connexion manuelle à SQLite.
    """
    # On peut simplement faire :
    return User.query.get(int(user_id))
