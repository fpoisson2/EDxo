# EDxo - Assistant pédagogique

EDxo automatise la création des plans cadres, des plans de cours et des grilles d'évaluation en quelques minutes en utilisant l'IA. Libérez-vous des tâches répétitives et recentrez votre travail sur vos étudiants !

Ceci est une application web Flask. L'application est structurée de manière modulaire grâce à l'utilisation des blueprints et de plusieurs extensions Flask.

## Table des matières

1. [Fonctionnalités](#fonctionnalités)
2. [Prérequis](#prérequis)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Exécution-de-lapplication](#exécution-de-lapplication)
6. [Tests](#tests)
7. [Déploiement](#déploiement)
8. [Structure-du-projet](#structure-du-projet)
9. [API et OAuth](#api-et-oauth)
10. [Licence](#licence)

## 1. Fonctionnalités

- **Authentification des utilisateurs** : Gestion des sessions utilisateurs avec Flask-Login.
- **Sécurité** : Protection CSRF avec Flask-WTF et gestion sécurisée des sessions.
- **Base de données** : Utilisation de SQLAlchemy avec SQLite (mode WAL) et gestion des migrations avec Flask-Migrate.
- **Planification des sauvegardes** : Planification automatique des sauvegardes de la base de données grâce à APScheduler.
- **Gestion des sessions** : Expiration automatique des sessions en fonction de l'activité.
- **Outils supplémentaires** : limitation du débit avec Flask-Limiter, et bien d'autres.
- **API REST sécurisée** : Accès aux programmes, cours et plans via un jeton personnel ou un flux OAuth 2.1 (PKCE, enregistrement dynamique). Un serveur MCP fournit également ces données via le protocole Model Context Protocol.

## 2. Prérequis

Avant de lancer l'application, assurez-vous d'avoir installé :

- Python 3.7+
- Virtualenv (recommandé)
- **Redis** (pour Celery, voir [Installation de Redis](#installation-de-redis))

## 3. Installation

### 3.1 Cloner le dépôt

```
git clone https://github.com/fpoisson2/edxo
cd edxo
```

### 3.2 Créer et activer un environnement virtuel

Pour créer un environnement virtuel, utilisez la commande suivante :

```
python3 -m venv venv
```
Pour activer l'environnement virtuel, procédez comme suit :

Sous Linux/MacOS :

```
source venv/bin/activate
```

Sous Windows :

```
venv\Scripts\activate
```
3.3 Installer les dépendances

Les dépendances sont déjà listées dans le fichier requirements.txt présent à la racine du projet. Installez-les avec la commande suivante :

```
pip install -r requirements.txt
pip install --upgrade -r requirements.txt
```
## 4. Configuration
### 4.1 Variables d'environnement

L'application utilise python-dotenv pour charger les variables d'environnement depuis un fichier .env. Créez un fichier .env à la racine du projet avec au moins :

```
SECRET_KEY='votre_cle_secrete'
RECAPTCHA_PUBLIC_KEY='votre_cle_public recaptcha'
RECAPTCHA_PRIVATE_KEY='votre_cle_secrete recaptcha'
RECAPTCHA_THRESHOLD=0.5
OPENAI_MODEL_SECTION='gpt-5'
OPENAI_MODEL_EXTRACTION='gpt-5-mini'
```

Vous pouvez définir d'autres variables spécifiques à votre environnement
`OPENAI_MODEL_SECTION` et `OPENAI_MODEL_EXTRACTION` contrôlent respectivement les modèles OpenAI utilisés pour la détection des sections et l'extraction de compétences.

### v4.2 Paramètres de l'application

L'application prend en charge deux configurations :

Production : Lit les paramètres depuis les variables d'environnement et configure la base de données dans database/programme.db.
Test : Utilise une base de données SQLite en mémoire et désactive la protection CSRF.
La configuration est gérée dans la fonction create_app située dans src/app/__init__.py.

## 5. Exécution de l'application
### 5.1 Mode Développement

Pour lancer l'application en mode développement :

```
export FLASK_APP=src/app/__init__.py
export FLASK_ENV=development
flask run
```
Cela lancera le serveur de développement avec le débogage activé.


### 5.2 Mode Production

Pour la production, il est recommandé d'utiliser un serveur WSGI tel que Gunicorn :

```
gunicorn -w 4 "src.app.__init__:create_app()"
```
Cette commande exécute l'application avec 4 processus de travail. Assurez-vous que vos variables d'environnement et configurations sont correctement définies pour la production.


## 6. Tests
Une configuration spécifique pour les tests est disponible dans le code de l'application. Pour exécuter les tests :

Lors de la création de l'instance de l'application, activez le mode test :

```
app = create_app(testing=True)
```

Utilisez votre framework de test préféré (par exemple, pytest ou unittest) pour écrire et lancer vos tests.

Exemple avec pytest :

```
pytest
```
Veillez à ce que vos tests soient isolés de la base de données de production en utilisant la configuration SQLite en mémoire fournie par la classe TestConfig.

## 7. Déploiement

Gunicorn : Comme indiqué ci-dessus, vous pouvez déployer l'application avec Gunicorn.

Proxy Inverse : Il est recommandé de faire tourner l'application derrière un proxy inverse (par exemple, Nginx) pour la terminaison SSL et l'équilibrage de charge.

Variables d'environnement : Assurez-vous toujours que les données sensibles comme SECRET_KEY soient gérées de manière sécurisée via les variables d'environnement.
## 8. Configuration des services systemd
Pour faciliter la gestion de l'application en production, utilisez systemd pour gérer les services.

### 8.1 Service Flask avec Gunicorn
Créez le fichier /etc/systemd/system/edxo.service avec le contenu suivant :

```
[Unit]
Description=Gunicorn instance to serve Flask app
After=network.target

[Service]
User='your_user_name'
Group=www-data
WorkingDirectory=/home/'your_user_name'/edxo
Environment="PATH=/home/'your_user_name'/edxo/venv/bin"
Environment="PYTHONPATH=/home/'your_user_name'edxo/src"
ExecStart=/home/'your_user_name'/edxo/venv/bin/gunicorn -w 1 -b 0.0.0.0:8000 src.wsgi:app --timeout 500

[Install]
WantedBy=multi-user.target
```

### 8.2 Service Celery Worker
Créez le fichier /etc/systemd/system/edxo-celery.service avec le contenu suivant :

```
[Unit]
Description=Celery Worker for EDxo
After=network.target

[Service]
User='your_user_name'
Group=www-data
WorkingDirectory=/home/'your_user_name'
Environment="PATH=/home/'your_user_name'/edxo/venv/bin"
Environment="PYTHONPATH=/home/'your_user_name'/edxo/src"
Environment="CELERY_WORKER=1"
ExecStart=/home/'your_user_name'/edxo/venv/bin/celery -A celery_app.celery worker --loglevel=info --concurrency=4 --hostname=worker2@%h
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 9. Installation de Redis
Redis est requis pour le fonctionnement de Celery en tant que broker de messages.

### 9.1 Installation sur Debian/Ubuntu
```
sudo apt update
sudo apt install redis-server
```

### 9.2 Vérification et activation du service Redis
Vérifiez que Redis fonctionne correctement :

```
sudo systemctl status redis
```
Pour activer Redis au démarrage du système :

```
sudo systemctl enable redis
```

### 10 Install de Gunicorn
Gunicorn est requis pour faire fonctionner l'environnement de production:
```
sudo apt update
sudo apt install gunicorn
```

### 8.3 Activation des services
Rechargez la configuration systemd et activez/démarrez les services :

```
sudo systemctl daemon-reload

sudo systemctl enable edxo.service
sudo systemctl start edxo.service

sudo systemctl enable edxo-celery.service
sudo systemctl start edxo-celery.service
```


## Structure du projet
```
edxo/
├── src/
│   ├── app/
│   │   ├── __init__.py         # Usine de création de l'application et configuration
│   │   ├── models.py           # Modèles de la base de données (ex. : User, BackupConfig)
│   │   └── routes/             # Blueprints pour les routes (ex. : cours, chat, programme, etc.)
│   ├── extensions.py           # Instances centralisées des extensions Flask (db, login_manager, etc.)
│   └── utils/                  # Modules utilitaires (scheduler, db_tracking, etc.)
├── templates/                  # Templates HTML
├── static/                     # Fichiers statiques (CSS, JS, images, documents)
├── .env                        # Variables d'environnement
├── requirements.txt            # Dépendances Python
└── README.md                   # Ce fichier
```

## API et OAuth

### Jeton personnel

Depuis l'interface web, ouvrez <em>Paramètres → Espace développeur</em> pour générer un jeton lié à votre compte. Ce jeton peut recevoir une durée de vie personnalisée et doit être envoyé dans l'en-tête <code>X-API-Token</code> de chaque requête.

```bash
curl -H "X-API-Token: VOTRE_TOKEN" https://example.com/api/programmes
```

La page <code>/help/api</code> liste l'ensemble des points d'accès disponibles.

### Flux OAuth 2.1

Pour les applications externes, l'API prend en charge le flux Authorization Code avec PKCE et l'enregistrement dynamique des clients.

- Métadonnées : <code>GET /.well-known/oauth-authorization-server</code>
- Inscription client : <code>POST /register</code>
- Autorisation utilisateur : <code>GET /authorize</code>
- Échange de code : <code>POST /token</code>

Les jetons émis sont liés à l'utilisateur qui a accordé l'accès et peuvent être présentés à l'API via <code>Authorization: Bearer &lt;token&gt;</code>.

### Serveur MCP

Le serveur FastMCP (« <code>src/mcp_server/server.py</code> ») expose les mêmes données via le protocole Model Context Protocol. Il accepte les jetons personnels ou OAuth dans l'en-tête <code>Authorization</code>.

## Licence
Ce projet est sous licence MIT.

N'hésitez pas à contribuer en ouvrant des issues ou en soumettant des pull requests. Pour toute question, veuillez contacter francis.poisson2@gmail.com.

