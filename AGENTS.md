# Guide du Référentiel (FR)

## Structure du projet et des modules
- Source: `src/` (application Flask). Blueprints dans `src/app/routes/`, templates dans `src/app/templates/`, assets statiques dans `src/static/`.
- Fabrique d’application: `src/app/__init__.py`; entrée WSGI: `src/wsgi.py` (Gunicorn utilise `create_app()`).
- Tâches/Celery: `src/celery_app.py` et `src/app/tasks/`.
- Base de données: `src/database/` (SQLite) et migrations dans `src/migrations/`.
- Utilitaires: `src/utils/`, configuration dans `src/config/`.
- Tests: `tests/` avec `conftest.py` et des fichiers `test_*.py`.

## Commandes de build, test et développement
- Installation: `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.
- Lancer (dev): `export FLASK_APP=src/app/__init__.py; export FLASK_ENV=development; flask run`.
- Worker Celery (local):
  - Depuis la racine du repo: `celery -A src.celery_app:celery worker --loglevel=info`.
  - Depuis le dossier `src/`: `celery -A celery_app:celery worker --loglevel=info`.
  - Redis requis; configurez `CELERY_BROKER_URL` et `CELERY_RESULT_BACKEND` dans `.env`.
- Docker: `docker-compose up --build` pour lancer l’API, Redis et Celery.
- Migrations: `flask db migrate -m "msg" && flask db upgrade`.
- Tests: `pytest -q`.
- Production: `gunicorn -w 4 "src.app.__init__:create_app()" --bind 0.0.0.0:5000`.

## Style de code et conventions de nommage
- Python 3.x, PEP 8, indentation 4 espaces.
- Fichiers/modules/fonctions: `snake_case`; classes: `PascalCase`; constantes: `UPPER_SNAKE_CASE`.
- Ajoutez les nouvelles routes sous `src/app/routes/` et les templates HTML dans `src/app/templates/`.
- Pas de secrets en dur. Utilisez `.env` (ignoré par Git) pour `SECRET_KEY`, `RECAPTCHA_PUBLIC_KEY`, `RECAPTCHA_PRIVATE_KEY`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`, ainsi que `CELERY_BROKER_URL` et `CELERY_RESULT_BACKEND`.

## Lignes directrices pour les tests
- Framework: `pytest`. Placez les tests dans `tests/` avec le préfixe `test_`.
- Fixtures: utilisez celles de `tests/conftest.py` (`app`, `client`). Les tests tournent sur SQLite en mémoire via `TestConfig` (définie dans `src/app/__init__.py`).
- Couvrez routes, modèles et flux d’authentification (p. ex. `/version`, redirections). Mockez les appels externes; utilisez Redis uniquement si nécessaire pour les tests Celery.

## Bonnes pratiques pour commits et PR
- Commits: concis, au présent. L’historique favorise des résumés courts en français (p. ex. `M2M cours-programme`, `Update programme.py`). Groupez les changements liés.
- Pull Requests: description claire, issues liées, étapes de test, et mention de toute migration BD. Ajoutez des captures d’écran/GIF pour les changements UI. Assurez-vous que `pytest` passe.
- Limitez la portée des PR et mettez à jour la documentation lors de modifications des commandes, routes ou de la structure.

## Tâches asynchrones (Celery) et notifications UI
- Pattern standard pour les opérations longues (plans-cadres, génération de grille, import):
  - Backend: déclencher une tâche Celery et retourner `task_id` (ex: `POST /programme/<id>/grille/generate`). Exposer un endpoint de statut JSON (ex: `GET /programme/api/task_status/<task_id>`), incluant `state` (`PENDING|PROGRESS|SUCCESS|FAILURE`) et un payload `{status,message,result}`.
  - Frontend: au clic sur l’action, désactiver le bouton, afficher un spinner et créer une notification « in-progress » via `addNotification('…', 'in-progress')`. Ensuite, poller l’endpoint de statut jusqu’à `SUCCESS`/`FAILURE`.
  - Succès: remplacer la notification par un message `success`, réactiver le bouton, mettre à jour l’UI (aperçu, lien d’application, etc.).
  - Échec: afficher une notification `error`, réactiver le bouton, laisser l’utilisateur relancer.
- Composants réutilisables:
  - Système de notifications global (menu cloche) dans `base.html` avec `addNotification(type='in-progress'|'success'|'error')`.
  - Exemple d’implémentation: générateur de plans-cadres et modal « Générer une grille (IA) » dans `view_programme.html` (désactivation du bouton + spinner, polling, notifications, prévisualisation, bouton « Appliquer »).
