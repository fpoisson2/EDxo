from main import create_app  # Import de l'application Flask
from utils.scheduler_instance import start_scheduler, schedule_backup
from app.models import db  # Import SQLAlchemy
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

app = create_app()

# Démarrer le scheduler
start_scheduler()

# Vérifier si la table backup_config existe avant de planifier la sauvegarde
with app.app_context():
    result = db.session.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_config';"
    )).fetchone()

    if result:  # Si la table existe, on active les sauvegardes
        schedule_backup(app)
    else:
        logger.warning("⚠️ Table 'backup_config' introuvable, planification des sauvegardes désactivée.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
