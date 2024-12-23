from flask_login import LoginManager
from utils import get_db_connection
from models import User

# Configure Flask-Login
login_manager = LoginManager()
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_view = 'main.login'

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM User WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['password'], user['role'])
    return None
