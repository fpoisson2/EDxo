import pytest
from src.app import create_app, db
from config.version import __version__

@pytest.fixture
def app():
    """
    Create and configure an instance of the application for testing.
    The database is created before tests and dropped afterward.
    """
    app = create_app(testing=True)
    
    with app.app_context():
        # Create tables in the (temporary/in-memory) database
        db.create_all()
        yield app
        # Cleanup: remove session and drop all tables
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """
    Provides a test client for simulating HTTP requests.
    """
    return app.test_client()

def test_version_endpoint(client):
    """
    Verifies that the /version endpoint returns the expected version number.
    """
    response = client.get('/version')
    assert response.status_code == 200, "Expected HTTP status 200."

    data = response.get_json()
    assert data is not None, "Response should be JSON."
    assert 'version' in data, "Response JSON should contain 'version' key."
    assert data['version'] == __version__, f"Version should be {__version__}."

def test_public_endpoint_redirection(client):
    """
    Checks that an attempt to access a protected endpoint redirects to the login page.
    (Here we assume that the '/' route is protected.)
    """
    response = client.get('/')
    # In testing mode, the user is not authenticated so a redirection should occur.
    assert response.status_code in (301, 302), "A redirection is expected for protected endpoints."

    location = response.headers.get("Location")
    assert location is not None, "A 'Location' header must be present upon redirection."
    assert "login" in location, "The redirection should point to the login page."

def test_static_files_access(client):
    """
    Verifies that accessing static files (e.g. /static/) does not require authentication.
    For a non-existent file, the server should return a 404 rather than a redirect.
    """
    response = client.get('/static/nonexistent_file.txt')
    assert response.status_code == 404, "A nonexistent static file should return 404 without redirection."

def test_protected_route_without_authentication(client):
    """
    Checks that a protected route (e.g. '/settings') redirects to the login page
    when no user is authenticated.
    """
    response = client.get('/settings', follow_redirects=False)
    assert response.status_code in (301, 302), "Accessing a protected route without authentication should redirect."
    
    location = response.headers.get("Location")
    assert location is not None, "The redirection must include a destination URL."
    assert "login" in location, "The redirection should point to the login page."
