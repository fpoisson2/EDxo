# Repository Guidelines

## Project Structure & Module Organization
- Source: `src/` (Flask app). Blueprints in `src/app/routes/`, templates in `src/app/templates/`, static assets in `src/static/`.
- App factory: `src/app/__init__.py`; WSGI entry: `src/wsgi.py` (Gunicorn uses `create_app()`).
- Tasks/Celery: `src/celery_app.py` and `src/app/tasks/`.
- Database: `src/database/` (SQLite file), migrations in `src/migrations/`.
- Utilities: `src/utils/`, configuration in `src/config/`.
- Tests: `tests/` with `conftest.py` and `test_*.py` files.

## Build, Test, and Development Commands
- Setup: `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.
- Run (dev): `export FLASK_APP=src/app/__init__.py; export FLASK_ENV=development; flask run`.
- Celery worker: `celery -A celery_app.celery worker --loglevel=info` (requires Redis).
- Docker: `docker-compose up --build` to run API, Redis, and Celery.
- Migrations: `flask db migrate -m "msg" && flask db upgrade`.
- Tests: `pytest -q`.
- Production: `gunicorn -w 4 "src.app.__init__:create_app()" --bind 0.0.0.0:5000`.

## Coding Style & Naming Conventions
- Python 3.x, PEP 8, 4‑space indentation.
- Files/modules/functions: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE_CASE`.
- Place new routes under `src/app/routes/` and HTML in `src/app/templates/`.
- Avoid hardcoded secrets. Use `.env` (ignored) for `SECRET_KEY`, `RECAPTCHA_*`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`, and `CELERY_*` URLs.

## Testing Guidelines
- Framework: `pytest`. Put tests in `tests/` named `test_*.py`.
- Use fixtures from `tests/conftest.py` (`app`, `client`). Tests run against in‑memory SQLite via `TestConfig`.
- Cover routes, models, and auth flows (e.g., `/version`, redirects). Mock external APIs; run Redis only when truly needed for Celery tests.

## Commit & Pull Request Guidelines
- Commits: concise, present‑tense. The history favors short French summaries (e.g., `M2M cours-programme`, `Update programme.py`). Group related changes.
- PRs: clear description, linked issues, steps to test, note any DB migration. Include screenshots/GIFs for UI changes. Ensure `pytest` passes.
- Scope changes narrowly and update docs when altering commands, routes, or structure.

