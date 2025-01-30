from app import create_app

# Create the Flask application instance
application = create_app()
app = application  # Gunicorn looks for 'application' by default, but we also provide 'app'

if __name__ == "__main__":
    application.run()