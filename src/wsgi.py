# src/wsgi.py
from .app import create_app  # <- import relatif

# Create the Flask application instance
application = create_app()
app = application  # exposer 'app' et 'application' est OK

if __name__ == "__main__":
    application.run()
