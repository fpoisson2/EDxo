FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Définir le répertoire de travail sur /
WORKDIR /

# Copier le fichier de dépendances et installer
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copier l'ensemble du projet
COPY . .

# Changer le répertoire de travail vers src
WORKDIR /src

# Exposer le port pour Gunicorn (ici 8000)
EXPOSE 5000

# Lancer l'application avec Gunicorn
CMD ["gunicorn", "-w", "4", "app.__init__:create_app()", "--bind", "0.0.0.0:5000"]
