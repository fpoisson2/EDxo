# routes/system.py
from flask import (
    Blueprint, 
    send_file, 
    current_app, 
    abort, 
    render_template, 
    flash, 
    redirect, 
    url_for,
    jsonify
)
from flask_login import login_required, current_user
from datetime import datetime
import os
from functools import wraps
from decorator import role_required, roles_required
from models import db, BackupConfig 
from sqlalchemy import text 
from forms import BackupConfigForm
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TimeField, BooleanField
from wtforms.validators import DataRequired, Email
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime
import os
from apscheduler.schedulers.background import BackgroundScheduler
from utils import send_backup_email, schedule_backup
from utilitaires.scheduler_instance import scheduler

system_bp = Blueprint('system', __name__)

@system_bp.route('/save_backup_config', methods=['POST'])
@roles_required('admin')
def save_backup_config():
    form = BackupConfigForm()
    if form.validate_on_submit():
        config = BackupConfig.query.first()
        if not config:
            config = BackupConfig()
            db.session.add(config)
        
        config.email = form.email.data
        config.frequency = form.frequency.data
        config.backup_time = form.backup_time.data.strftime('%H:%M')
        config.enabled = form.enabled.data
        
        db.session.commit()
        
        # Restart scheduler if running
        scheduler.remove_all_jobs()
        if config.enabled:
            scheduler.start()
            schedule_backup(current_app)
            
        flash('Configuration sauvegardée', 'success')
    return redirect(url_for('system.management'))

@system_bp.route('/manual_backup', methods=['POST'])
@roles_required('admin')
def manual_backup():
    config = BackupConfig.query.first()
    if not config or not config.email:
        return jsonify({'message': 'Email de sauvegarde non configuré'}), 400
    
    try:
        send_backup_email(current_app, config.email, current_app.config['DB_PATH'])
        return jsonify({'message': 'Sauvegarde envoyée avec succès'})
    except Exception as e:
        return jsonify({'message': f'Erreur: {str(e)}'}), 500

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

@system_bp.route('/management')
@roles_required('admin')
def management():
    form = BackupConfigForm()
    config = BackupConfig.query.first()
    
    if config:
        form.email.data = config.email
        form.frequency.data = config.frequency
        form.backup_time.data = datetime.strptime(config.backup_time, '%H:%M').time()
        form.enabled.data = config.enabled
        
    return render_template('system/management.html', form=form)

@system_bp.route('/system/download-db')
@roles_required('admin')
def download_db():
    if not check_db_status():
        flash("La base de données n'est pas dans un état cohérent pour le téléchargement.", "error")
        return redirect(url_for('system.management'))

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

