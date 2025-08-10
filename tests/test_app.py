import pytest
from config.version import __version__
from werkzeug.security import generate_password_hash, check_password_hash

def get_model_by_name(model_name, db):
    """
    Iterate over the model registry to find a model by its class name.
    """
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None

def test_version_endpoint(client):
    """
    Verifies that the /version endpoint returns the expected version number.
    """
    response = client.get('/version')
    assert response.status_code == 200, "Expected HTTP status 200."
    
    data = response.get_json()
    assert data is not None, "Response should be JSON."
    assert 'version' in data, "Response JSON should contain a 'version' key."
    assert data['version'] == __version__, f"Version should be {__version__}."

def test_public_endpoint_redirection(client):
    """
    Checks that an attempt to access a protected endpoint redirects to the login page.
    (Here we assume that the '/' route is protected.)
    """
    response = client.get('/')
    # In testing mode, if the user is not authenticated a redirection should occur.
    assert response.status_code in (301, 302), "A redirection is expected for protected endpoints."

    location = response.headers.get("Location")
    assert location is not None, "A 'Location' header must be present upon redirection."
    assert "login" in location, "The redirection should point to the login page."

def test_static_files_access(client):
    """
    Verifies that accessing static files (e.g., /static/) does not require authentication.
    For a non-existent file, the server should return a 404 rather than a redirect.
    """
    response = client.get('/static/nonexistent_file.txt')
    assert response.status_code == 404, "A nonexistent static file should return 404 without redirection."

def test_protected_route_without_authentication(client):
    """
    Checks that a protected route (e.g., '/settings') redirects to the login page
    when no user is authenticated.
    """
    response = client.get('/settings', follow_redirects=False)
    assert response.status_code in (301, 302), "Accessing a protected route without authentication should redirect."
    
    location = response.headers.get("Location")
    assert location is not None, "The redirection must include a destination URL."
    assert "login" in location, "The redirection should point to the login page."

def test_create_admin_without_direct_import(app):
    """
    Create an admin user using the model registry (without importing the model directly)
    and verify its creation.
    """
    with app.app_context():
        from src.app import db  # Access the db instance from your app
        
        # Retrieve the User model from the registry using our helper function.
        User = get_model_by_name("User", db)
        assert User is not None, "User model not found in registry."

        # Create a new admin user.
        admin = User(
            username="admin",
            password="adminpass",  # For tests, plain text is acceptable.
            role="admin",
            credits=100.0
        )
        db.session.add(admin)
        db.session.commit()

        # Retrieve the user to verify that it was added successfully.
        retrieved_user = User.query.filter_by(username="admin").first()
        assert retrieved_user is not None, "Admin user was not created."
        assert retrieved_user.role == "admin", "User role should be admin."
        assert retrieved_user.credits == 100.0, "User credits should be 100.0."

def fake_requests_post(url, data, **kwargs):
    """
    Simule l'appel à l'API reCAPTCHA en renvoyant un résultat valide.
    """
    class FakeResponse:
        status_code = 200
        def json(self):
            return {'success': True, 'score': 1.0}
    return FakeResponse()


def test_login_with_admin(client, app, monkeypatch):
    """
    Crée un utilisateur admin (s'il n'existe pas) avec un mot de passe hashé,
    puis tente de se connecter avec cet utilisateur. Après une connexion réussie,
    Flask-Login doit stocker l'ID utilisateur dans la session.
    """
    # Patch la fonction requests.post pour simuler la vérification reCAPTCHA
    monkeypatch.setattr("requests.post", fake_requests_post)

    with app.app_context():
        from src.app import db  # Accès à l'instance de la base de données
        User = get_model_by_name("User", db)
        assert User is not None, "User model not found in registry."

        # Assure que l'utilisateur admin existe.
        admin = User.query.filter_by(username="admin").first()
        if admin is None:
            hashed_password = generate_password_hash("adminpass")
            admin = User(
                username="admin",
                password=hashed_password,
                role="admin",
                credits=100.0
            )
            db.session.add(admin)
            db.session.commit()
        
        # Stocke l'id de l'admin pour les assertions ultérieures.
        admin_id = admin.id

    # Prépare les données de login en ajoutant le token reCAPTCHA fictif.
    login_data = {
        "username": "admin",
        "password": "adminpass",
        "recaptcha_token": "dummy_token",  # Valeur factice pour le test
        "submit": "Se connecter"  # Inclure si votre formulaire l'utilise.
    }
    response = client.post('/login', data=login_data, follow_redirects=True)
    assert response.status_code == 200, "Login should eventually return HTTP 200 after redirection."

    # Vérifie que la session contient bien l'ID de l'utilisateur (Flask-Login stocke généralement dans _user_id)
    with client.session_transaction() as session:
        assert "_user_id" in session, "User not logged in; session missing '_user_id'."
        # L'ID est stocké en tant que chaîne. Vérifiez qu'il correspond à celui de l'admin.
        assert session["_user_id"] == str(admin_id), "Logged in user id does not match admin's id."


def test_chat_model_config_defaults(app):
    with app.app_context():
        from src.app import db
        ChatModelConfig = get_model_by_name("ChatModelConfig", db)
        assert ChatModelConfig is not None, "ChatModelConfig model not found."
        cfg = ChatModelConfig.get_current()
        assert cfg.chat_model is not None
        assert cfg.tool_model is not None
