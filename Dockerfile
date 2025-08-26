FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Travailler depuis /app pour que "src" soit importable
WORKDIR /app

# Copier le fichier de dépendances et installer
COPY requirements.txt .
# Lighter system deps for WeasyPrint (HTML->PDF) + fonts
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
       fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip && pip install -r requirements.txt

# Copier l'ensemble du projet dans /app
COPY . .

# Exposer le port pour Gunicorn/UvicornWorker (ASGI)
EXPOSE 8000

# Démarrer l'ASGI hub: Starlette + Flask via WsgiToAsgi
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000", "src.asgi:app", "--timeout", "500"]
