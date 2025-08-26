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

## Tâches asynchrones unifiées (Celery) et notifications UI
- Endpoints unifiés:
  - Statut JSON: `GET /tasks/status/<task_id>` → `{task_id,state,message,meta,result}`.
  - Streaming SSE: `GET /tasks/events/<task_id>` → événements `open|progress|ping|done`.
  - Page de suivi: `GET /tasks/track/<task_id>` (utilise `task_status.html`).
- Orchestrateur Frontend: `static/js/task_orchestrator.js`
  - `EDxoTasks.startCeleryTask(url, fetchOpts, {title,startMessage})`: lance la tâche, ajoute une notification « in-progress » avec lien `/tasks/track/<task_id>`, et ouvre un modal de suivi (stream + JSON).
  - `EDxoTasks.openTaskModal(taskId, {title,statusUrl,eventsUrl,onDone})`: ouvre le modal sur un `task_id` existant.
- Notifications enrichies (base.html):
  - En cours: `addNotification('…', 'in-progress', '/tasks/track/<task_id>')` pour permettre d’ouvrir le suivi.
  - Succès: si le payload contient `validation_url`, la notification pointe vers la page de validation/comparaison; sinon fallback (reviewUrl, planCadreUrl, plan_de_cours_url).
- Modal générique de suivi (injecté par l’orchestrateur):
  - Onglets minimalistes: flux (stream), affichage JSON.
  - Bouton « Aller à la validation » si `validation_url` présent dans le payload final.
- Configuration IA centralisée:
  - Page dédiée: `GET /settings/generation` pour choisir le modèle, l’effort de raisonnement et la verbosité.
  - Les prompts spécifiques demeurent dans leurs pages respectives (Plan-cadre, Plan de cours, OCR), accessibles depuis le menu Paramètres.
- Importations (PDF devis/logigrammes/grilles/plans):
  - Appliquer le même pattern que l’import devis ministériel: POST déclenche tâche → retourne `task_id` → suivi via `/tasks/track/<task_id>` → redirection vers page de validation/comparaison à la fin.
- Exemples rapides:
  - Lancer génération: `EDxoTasks.startCeleryTask('/api/plan_cadre/123/generate', {method:'POST'}, {title:'Générer un plan-cadre'})`.
  - Ouvrir un suivi existant: `EDxoTasks.openTaskModal(taskId, {title:'Import en cours'})`.

### Principe général

- Tâches exécutées via Celery: chaque action lourde est déclenchée côté serveur et retourne `{ task_id }`.
- Suivi unifié: endpoints partagés `GET /tasks/status/<task_id>` (JSON) et `GET /tasks/events/<task_id>` (SSE) + page `GET /tasks/track/<task_id>`.
- Orchestrateur Frontend: `static/js/task_orchestrator.js` expose `EDxoTasks.startCeleryTask()` et `EDxoTasks.openTaskModal()`.
- Modal de suivi: affiche flux (stream), JSON, et (optionnel) le prompt utilisateur; propose un lien de validation si disponible.
- Notifications enrichies: ajout de notifications « in-progress » et « success » avec lien de suivi/validation.
- Configuration IA centralisée: `/settings/generation` (modèle, effort de raisonnement, verbosité), avec pages dédiées par domaine (Plan‑cadre, Plan de cours, OCR, etc.).

### Patron d’implémentation côté serveur

1) Créer un endpoint de déclenchement (POST) qui:
   - Valide les entrées minimales (ex.: IDs, fichiers).
   - Lance la tâche Celery: `task = my_task.delay(...)`
   - Retourne `jsonify({ 'task_id': task.id })`, HTTP 202.

2) Dans la tâche Celery:
   - Publier la progression: `self.update_state(state='PROGRESS', meta={'message': '...', 'step': '...', 'progress': 0-100})`.
   - Renvoyer un `dict` final:
     - `status: 'success' | 'error'` + `message` en cas d’erreur.
     - `validation_url` vers la page de validation/comparaison.
     - Toute donnée utile au front (ex.: `result`, `usage`, etc.).

3) Vérifier que les endpoints unifiés existent et sont exposés (`src/app/routes/tasks.py`).

### Patron d’implémentation côté client

Pour toute action (génération, amélioration, import), appeler:

```js
await EDxoTasks.startCeleryTask('/api/.../start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
  body: JSON.stringify(payload)
}, {
  title: 'Titre de la tâche',
  startMessage: 'En cours…',
  userPrompt: promptOptionnel,
  onDone: (data) => { /* hook si besoin */ }
});
```

- Le modal s’ouvre automatiquement et se met à jour (SSE + polling).
- À la fin, si `validation_url` est présent, le bouton « Aller à la validation » s’active et une notification « success » est ajoutée avec le lien.

### Exemples supplémentaires

- Génération Plan‑cadre: `POST /api/plan_cadre/<plan_id>/generate`
- Amélioration Plan‑cadre: `POST /api/plan_cadre/<plan_id>/improve` (ou section ciblée)
- Génération Plan de cours: `POST /api/plan_de_cours/<plan_id>/generate` → `validation_url=/plan_de_cours/review/<id>?task_id=...`
- Import Plan‑cadre (DOCX): `POST /plan_cadre/<plan_id>/import_docx_start` → `validation_url=/plan_cadre/<id>/review?task_id=...`
- Génération Grille de cours: `POST /programme/<programme_id>/grille/generate` → `validation_url=/programme/<id>/grille/review?task_id=...`
- Génération Logigramme compétences: `POST /programme/<programme_id>/competences/logigramme/generate` → `validation_url=/programme/<id>/competences/logigramme`
- Import Grille PDF: `POST /grille/import` → `validation_url=/confirm_grille_import/<task_id>`
- Import Devis ministériel PDF (simplifié):
  - Démarrage: `POST /programme/<programme_id>/competences/import_pdf/start` avec `FormData(file=pdf)` → `{ task_id }`
  - Suivi: `/tasks/track/<task_id>` (modal unifié), notification in-progress avec lien de suivi
  - Validation: le worker fournit `validation_url=/programme/<programme_id>/competences/import/review?task_id=...` (comparaison JSON↔BD; confirmation via formulaire existant)

Pour une importation de fichier (PDF/DOCX), construire un `FormData` et appeler `EDxoTasks.startCeleryTask()` avec `body: formData` sans `Content-Type` (laissez le navigateur définir `multipart/form-data`).

### Points d’attention

- Toute tâche doit prévoir un `validation_url` pour guider l’utilisateur vers la comparaison/validation.
- Les prompts spécifiques restent dans leurs pages: Plan‑cadre, Plan de cours, OCR.
- La configuration IA (modèle/raisonnement/verbosité) se fait dans `/settings/generation`.
- Le modal peut afficher le prompt utilisateur (`userPrompt`) si fourni côté UI.

### Nettoyage

- Utiliser les endpoints unifiés `/tasks/status|events|track` pour tout suivi.
- Déprécier les anciens endpoints de statut/stream spécifiques dès migration.
