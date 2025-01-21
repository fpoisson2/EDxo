# routes/system.py
from flask import (
    Blueprint, 
    send_file, 
    current_app, 
    abort, 
    render_template, 
    flash, 
    redirect, 
    url_for
)
from flask_login import login_required, current_user
from datetime import datetime
import os
from functools import wraps
from decorator import role_required, roles_required
from models import db  # Ajout de cet import
from sqlalchemy import text  # Ajout de cet import

system_bp = Blueprint('system', __name__)

def check_db_status():
    try:
        # Forcer un checkpoint WAL avant le téléchargement
        db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
        db.session.commit()
        
        # Vérifier l'intégrité de la base de données
        result = db.session.execute(text("PRAGMA integrity_check;"))
        integrity = result.scalar()
        
        return integrity == 'ok'
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la vérification de la BD: {e}")
        return False

@system_bp.route('/system')
@roles_required('admin')
def system_management():
    return render_template('system/management.html')

@system_bp.route('/system/download-db')
@roles_required('admin')
def download_db():
    if not check_db_status():
        flash("La base de données n'est pas dans un état cohérent pour le téléchargement.", "error")
        return redirect(url_for('system.system_management'))

    # Chemin vers la base de données
    db_path = os.path.abspath('programme.db')
    
    # Vérifiez que le fichier existe
    if not os.path.exists(db_path):
        abort(404)
        
    # Créez un nom de fichier avec la date
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'programme_backup_{timestamp}.db'
    
    return send_file(
        db_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/x-sqlite3'
    )