# decorators.py
from functools import wraps
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required
from flask_ckeditor import CKEditor

def role_required(required_role, default_redirect='main.index'):
    """
    Decorator to restrict access to users with a specific role.
    Flashes a message and redirects back to the referring page or a default page.
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user_role = getattr(current_user, 'role', None)
            if user_role != required_role:
                flash("Vous n'avez pas la permission d'accéder à cette page.", "warning")
                # Redirect back to the referring page or to the default page
                return redirect(request.referrer or url_for(default_redirect))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def roles_required(*required_roles, default_redirect='main.index'):
    """
    Decorator to restrict access to users with any of the specified roles.
    Flashes a message and redirects back to the referring page or a default page.
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user_role = getattr(current_user, 'role', None)
            if user_role not in required_roles:
                flash("Vous n'avez pas la permission d'accéder à cette page.", "warning")
                # Redirect back to the referring page or to the default page
                return redirect(request.referrer or url_for(default_redirect))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def ensure_profile_completed(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_first_connexion:
            flash('Veuillez compléter votre profil avant de continuer.', 'warning')
            return redirect(url_for('main.welcome'))
        return f(*args, **kwargs)
    return decorated_function