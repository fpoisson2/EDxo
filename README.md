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
9. [Licence](#licence)

## 1. Fonctionnalités

- **Authentification des utilisateurs** : Gestion des sessions utilisateurs avec Flask-Login.
- **Sécurité** : Protection CSRF avec Flask-WTF et gestion sécurisée des sessions.
- **Base de données** : Utilisation de SQLAlchemy avec SQLite (mode WAL) et gestion des migrations avec Flask-Migrate.
- **Planification des sauvegardes** : Planification automatique des sauvegardes de la base de données grâce à APScheduler.
- **Gestion des sessions** : Expiration automatique des sessions en fonction de l'activité.
- **Outils supplémentaires** : limitation du débit avec Flask-Limiter, et bien d'autres.

## 2. Prérequis

Avant de lancer l'application, assurez-vous d'avoir installé :

- Python 3.7+
- Virtualenv (recommandé)

## 3. Installation

### 3.1 Cloner le dépôt

```
git clone https://github.com/fpoisson2/edxo
cd edxo
```

### 3.2 Créer et activer un environnement virtuel

Pour créer un environnement virtuel, utilisez la commande suivante :

```
python -m venv venv
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
```
## 4. Configuration
### 4.1 Variables d'environnement

L'application utilise python-dotenv pour charger les variables d'environnement depuis un fichier .env. Créez un fichier .env à la racine du projet avec au moins :

``` 
SECRET_KEY=votre_cle_secrete
```

Vous pouvez définir d'autres variables spécifiques à votre environnement

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
Cela lancera le serveur de développement avec le débogage activé.
```

### 5.2 Mode Production

Pour la production, il est recommandé d'utiliser un serveur WSGI tel que Gunicorn :

```
gunicorn -w 4 "src.app.__init__:create_app()"
Cette commande exécute l'application avec 4 processus de travail. Assurez-vous que vos variables d'environnement et configurations sont correctement définies pour la production.
```

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

## 8. Structure du projet
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

## 9. Licence
Ce projet est sous licence MIT.

N'hésitez pas à contribuer en ouvrant des issues ou en soumettant des pull requests. Pour toute question, veuillez contacter francis.poisson2@gmail.com.


