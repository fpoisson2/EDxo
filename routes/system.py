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
    jsonify,
    request
)
from flask_login import login_required, current_user
from datetime import datetime
import os
from functools import wraps
from decorator import role_required, roles_required
from models import db, BackupConfig, DBChange, User
from sqlalchemy import text 
from sqlalchemy.orm import joinedload
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
from utils import send_backup_email
from utilitaires.scheduler_instance import scheduler, schedule_backup
import pytz
import subprocess

import logging

# Configuration de base du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        config.backup_time = form.backup_time.data.strftime('%H:%M')  # Déjà en UTC
        config.enabled = form.enabled.data
        
        db.session.commit()
        scheduler.remove_all_jobs()
        
        if config.enabled:
            schedule_backup(current_app)
        
        flash('Configuration sauvegardée', 'success')
    else:
        flash('Erreur de validation du formulaire.', 'danger')
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

@system_bp.route('/get_current_time')
@roles_required('admin')
def get_current_time():
    user_timezone = 'Europe/Paris'  # Remplacez par la méthode de récupération dynamique si nécessaire
    now_utc = datetime.now(pytz.UTC)
    local_tz = pytz.timezone(user_timezone)
    now_local = now_utc.astimezone(local_tz)
    
    return jsonify({
        'current_time_utc': now_utc.strftime('%Y-%m-%d %H:%M:%S'),
    })

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
   
    try:
        jobs = scheduler.get_jobs()
        next_backup_times = [
            {
                'id': job.id,
                'next_run_time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S UTC') if job.next_run_time else 'Non planifié'
            }
            for job in jobs if job.id and job.id.endswith('_backup')
        ]
        logger.info(f"Jobs trouvés: {next_backup_times}")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des jobs: {e}")
        next_backup_times = []
   
    changes = db.session.query(  
        DBChange.id,
        DBChange.timestamp,
        DBChange.operation,
        DBChange.table_name,
        DBChange.record_id,
        DBChange.changes,
        User.username
    ).outerjoin(User, DBChange.user_id == User.id)\
     .order_by(DBChange.timestamp.desc())\
     .limit(20)\
     .all()
   
    # Désérialiser 'changes' si c'est une chaîne JSON
    for change in changes:
        if isinstance(change.changes, str):
            try:
                change.changes = json.loads(change.changes)
            except json.JSONDecodeError:
                change.changes = {}
   
    now_utc = datetime.now(pytz.UTC)
   
    return render_template(
        'system/management.html',
        form=form,
        next_backup_times=next_backup_times,
        current_time_utc=now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
        changes=changes
    )

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

@system_bp.route('/get_changes')
def get_changes():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    
    changes = db.session.query(
        DBChange.id,
        DBChange.timestamp,
        DBChange.operation,
        DBChange.table_name,
        DBChange.record_id,
        DBChange.changes,
        User.username
    ).outerjoin(User, DBChange.user_id == User.id)\
     .order_by(DBChange.timestamp.desc())\
     .paginate(page=page, per_page=size)

        
    return jsonify({
        'changes': [{
            'timestamp': change.timestamp.isoformat(),
            'username': change.username if change.username else 'Système',
            'operation': change.operation,
            'table_name': change.table_name,
            'record_id': change.record_id,
            'changes': change.changes
        } for change in changes.items]
    })
