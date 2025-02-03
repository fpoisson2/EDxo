# src/extensions.py

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_ckeditor import CKEditor
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_bcrypt import Bcrypt


limiter = Limiter(key_func=get_remote_address)
db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
ckeditor = CKEditor()
csrf = CSRFProtect()
