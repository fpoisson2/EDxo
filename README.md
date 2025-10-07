# EDxo — Assistant pédagogique

EDxo automatise la création des plans‑cadres, des plans de cours et des grilles d’évaluation grâce à l’IA (OpenAI Responses). 

L’application web met l’accent sur des workflows guidés, un suivi de tâches unifié (Celery) et une configuration IA par domaine.

- Composants clés: Flask (application), Celery (tâches), Starlette (hub ASGI pour SSE), serveur MCP (Model Context Protocol) et OAuth 2.1.

## Table des matières

1. Fonctionnalités
2. Prérequis
3. Installation
4. Configuration
5. Démarrage
6. Tests
7. Tâches et Suivi
8. Déploiement
9. Structure du projet
10. API et OAuth
11. MCP
12. Licence

## Fonctionnalités

- Plan‑cadre: génération/amélioration (global/section), import DOCX, export DOCX, page de comparaison/validation.
- Plan de cours: génération globale, calendrier, évaluations, amélioration par champ; review avant/après avec confirm/revert; export DOCX.
- OCR/Imports: devis ministériels PDF, grilles PDF via FormData; suivi unifié; validation finale.
- Grilles/Logigrammes: génération dédiée avec paramètres IA par domaine.
- Chat: modèles/outils configurables; effort de raisonnement et verbosité ajustables.
- Tâches unifiées: Celery + Redis, streaming texte et résumé du raisonnement (SSE), modal de suivi, notifications enrichies, annulation.
- Sécurité: Auth Flask‑Login, CSRF, reCAPTCHA, rate‑limit; API sécurisée (X‑API‑Token, OAuth 2.1), serveur MCP.

## Prérequis

- Python 3.12
- Virtualenv (recommandé)
- Redis (broker et backend Celery) en local ou via Docker
- Optionnel: Docker et Docker Compose

## Installation

1) Cloner et créer l’environnement virtuel

```
git clone https://github.com/fpoisson2/edxo
cd edxo
python -m venv venv
source venv/bin/activate
```

2) Installer les dépendances

```
pip install -r requirements.txt
```

## Configuration

Créez un fichier `.env` à la racine avec au minimum:

```
SECRET_KEY=une_chaine_secrete
RECAPTCHA_PUBLIC_KEY=...
RECAPTCHA_PRIVATE_KEY=...
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
# Facultatif
LOG_LEVEL=INFO
OPENAI_API_KEY=...
# Optionnel
RATELIMIT_STORAGE_URI=memory://
EASYMDE_USE_CDN=1
```

Notes

- Les clés OpenAI ne doivent jamais être codées en dur; la clé utilisateur peut être fournie côté profil pour débiter ses crédits.
- Des barèmes par défaut existent pour la tarification (gpt‑5, gpt‑5‑mini, gpt‑5‑nano) et peuvent être configurés dans la table `OpenAIModel`.
- Les tests n’exigent pas de clé OpenAI ni de Redis; la configuration de test (`TestConfig`) utilise SQLite en mémoire, désactive CSRF et règle le rate‑limit en mémoire.

## Démarrage

### Développement (Flask WSGI)

```
export FLASK_APP=src/app/__init__.py
export FLASK_ENV=development
flask run
```

Lancer le worker Celery local

```
celery -A src.celery_app:celery worker --loglevel=info
```

Astuce: au premier démarrage non‑test, une table SQLite est initialisée et un utilisateur admin est créé si absent (`username: admin`, mot de passe par défaut défini à la création; changez‑le immédiatement dans l’UI).

### ASGI (recommandé en production)

```
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 src.asgi:app
```

Remarque: le flux SSE des tâches (`GET /tasks/events/<task_id>`) est servi côté ASGI pour éviter de bloquer des workers WSGI. Désactivez le buffering côté reverse‑proxy pour ce chemin.

### Docker Compose

```
docker-compose up --build
```

Services: `app` (ASGI), `redis`, `celery`. Volumes: DB, uploads, pdfs, txt (persistants).

## Tests

Les tests utilisent `pytest` avec SQLite en mémoire.

```
pytest -q
```

## Tâches et Suivi

- Endpoints unifiés
  - Statut JSON: `GET /tasks/status/<task_id>` → `{task_id,state,message,meta,result}`
  - Streaming SSE: `GET /tasks/events/<task_id>` → événements `open|progress|ping|done` (servi par le hub ASGI)
  - Page de suivi: `GET /tasks/track/<task_id>` (template générique)
  - Annulation: `POST /tasks/cancel/<task_id>` (révocation + drapeau Redis coopératif)
- Orchestrateur Frontend (`static/js/task_orchestrator.js`): `EDxoTasks.startCeleryTask(url, fetchOpts, {title,startMessage,streamEl,summaryEl,onDone})`
- Les tâches publient `meta.stream_chunk`/`stream_buffer` et `meta.reasoning_summary` pour afficher le flux et le résumé de raisonnement en temps réel.

## Déploiement

### Docker Compose

```
docker-compose up --build
```

### Gunicorn (ASGI recommandé)

```
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 src.asgi:app
```

Si vous utilisez un reverse‑proxy, désactivez le buffering sur la route SSE (`/tasks/events/*`).

### Redis (Debian/Ubuntu)

```
sudo apt update && sudo apt install -y redis-server
sudo systemctl enable --now redis
```

## Frontend React (Vite)

Un client React TypeScript réside dans `frontend/` pour découpler l’interface du backend Flask.

- Installation: `cd frontend && npm install`
- Configuration: copiez `.env.example` en `.env.development` et ajustez `VITE_API_BASE_URL`
- Développement: `npm run dev` (proxy `/api`, `/auth`, `/tasks` vers Flask par défaut)
- Qualité: `npm run lint`; build de production avec `npm run build`

## Structure du projet

```
edxo/
├── src/
│   ├── app/
│   │   ├── __init__.py        # Fabrique Flask (create_app), enregistrement des blueprints
│   │   ├── models.py          # Modèles SQLAlchemy
│   │   ├── routes/            # Blueprints (plan_cadre, plan_de_cours, api, tasks, ocr, etc.)
│   │   ├── tasks/             # Tâches Celery (génération, import, ocr, grilles, logigramme)
│   │   └── templates/         # Templates Jinja2
│   ├── static/                # JS/CSS/images (dont task_orchestrator.js)
│   ├── config/                # Config, version, gunicorn, env
│   ├── database/              # SQLite + WAL (fichiers DB)
│   ├── migrations/            # Migrations Alembic (Flask-Migrate)
│   ├── celery_app.py          # Initialisation Celery et Task context Flask
│   ├── asgi.py                # Hub ASGI (Starlette): SSE + WSGI(Flask)
│   └── wsgi.py                # Entrée WSGI alternative
├── tests/                     # Pytest (fixtures app/client, tests unitaires)
├── OPENAI_USAGE.md            # Inventaire des appels IA
├── docker-compose.yml         # Déploiement conteneurisé
└── requirements.txt           # Dépendances Python
```

## API et OAuth

### Jeton personnel

Depuis l’UI: Paramètres → Espace développeur → générer un jeton. Transmettre via `X-API-Token`.

```
curl -H "X-API-Token: VOTRE_TOKEN" https://example.com/api/programmes
```

### Flux OAuth 2.1 (PKCE)

Métadonnées: `GET /.well-known/oauth-authorization-server`, inscription client: `POST /register`, autorisation: `GET /authorize`, échange: `POST /token`. Présenter `Authorization: Bearer <token>`.

## MCP

- Serveur MCP FastMCP: `src/mcp_server/server.py` expose ressources/outils (recherche et accès aux documents/objets du domaine) et est monté sous `/sse` via l’app ASGI.
- Authentification: accepte jetons personnels et OAuth; si FastMCP n’est pas disponible, un fallback inerte est chargé (les imports/routages restent valides).

## Licence

Projet sous licence MIT.

Contributions bienvenues (issues/PR). Pour toute question: francis.poisson2@gmail.com.
