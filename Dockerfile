FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Travailler depuis /app pour que "src" soit importable
WORKDIR /app

# Copier le fichier de dépendances et installer
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copier l'ensemble du projet dans /app
COPY . .

# Exposer le port pour Gunicorn/UvicornWorker (ASGI)
EXPOSE 8000

# Démarrer l'ASGI hub: Starlette + Flask via WsgiToAsgi
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000", "src.asgi:app", "--timeout", "500"]
