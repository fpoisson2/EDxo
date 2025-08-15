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

## Voix (Quickstart)
- Dépendances: `pip install 'openai-agents[voice]' numpy sounddevice`.
- Variable d’environnement: configurez `OPENAI_API_KEY` dans `.env` (ou dans votre environnement shell).
- Exécuter (micro 3s): `python -m src.scripts.voice_agent --seconds 3`.
  - Option `--silence`: envoie un buffer silencieux (utile pour tester l’audio de sortie).
  - Option `--samplerate`: par défaut `24000` (mono, `int16`).
- Flux: STT (transcription) → agent EDxo (handoffs/outils) → TTS (audio).
- Dépannage audio:
  - Assurez-vous d’avoir un périphérique d’entrée/sortie par défaut configuré.
  - Sous Linux, l’utilisateur doit appartenir au groupe audio; sous macOS, accordez l’accès micro.
  - Si la lecture est hachée, baissez `--samplerate` ou augmentez `--seconds`.

## Realtime (conversation continue, FR)
- Prérequis: `export OPENAI_API_KEY=...` (ou utilisez `--api-key`).
- Lancer (sans micro): `python -m src.scripts.realtime_voice_agent`.
- Lancer (avec micro local): `python -m src.scripts.realtime_voice_agent --mic`.
  - Options utiles:
    - `--model gpt-4o-realtime-preview` (par défaut)
    - `--voice alloy` (autres: `echo`, `fable`, `onyx`, `nova`, `shimmer`)
    - `--vad-threshold 0.5`, `--silence-ms 200`, `--prefix-padding-ms 300`
    - `--no-greeting` pour ne pas envoyer le message d’accueil
- Fonctionnement: ouvre une session Realtime avec VAD serveur; le modèle parle en temps réel et les transcriptions sont affichées dans le terminal (FR).
- Remarques:
  - L’audio d’E/S est géré par la session Realtime; pour un contrôle audio local (micro/haut-parleur) côté Python, utilisez `src/scripts/voice_agent.py`.
  - Le flag `--mic` tente de diffuser le PCM16 du micro vers la session Realtime via l’API du SDK. Si votre version du SDK ne fournit pas cette méthode, un avertissement s’affiche et la session reste text→audio uniquement.

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
