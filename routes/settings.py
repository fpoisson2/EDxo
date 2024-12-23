from flask import Blueprint, request, render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from constants import SECTIONS  # Importer la liste des sections
import sqlite3
from decorator import role_required, roles_required
from forms import (
    GlobalGenerationSettingsForm
)

from utils import get_db_connection

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

@settings_bp.route('/parametres')
@login_required  # Cette route nécessite que l'utilisateur soit connecté
def parametres():
    return render_template('parametres.html')

@settings_bp.route('/generation', methods=['GET', 'POST'])
@role_required('admin')
def edit_global_generation_settings():
    form = GlobalGenerationSettingsForm()
    conn = get_db_connection()

    if request.method == 'GET':
        # Retrieve the current OpenAI key for the logged-in user
        user_id = current_user.id
        openai_key_setting = conn.execute('SELECT openai_key FROM User WHERE id = ?', (current_user.id,)).fetchone()
        form.openai_key.data = openai_key_setting['openai_key'] if openai_key_setting else ''

        # Ensure the form sections match the SECTIONS list length
        current_entries = len(form.sections)
        required_entries = len(SECTIONS)
        if current_entries < required_entries:
            for _ in range(required_entries - current_entries):
                form.sections.append_entry()
        elif current_entries > required_entries:
            for _ in range(current_entries - required_entries):
                form.sections.pop_entry()

        # Fill the form with the existing settings for each section
        settings = conn.execute('SELECT * FROM GlobalGenerationSettings').fetchall()
        for i, section in enumerate(SECTIONS):
            setting = next((s for s in settings if s['section'] == section), None)
            if setting:
                form.sections[i].use_ai.data = bool(setting['use_ai'])
                form.sections[i].text_content.data = setting['text_content']
            else:
                form.sections[i].use_ai.data = False
                form.sections[i].text_content.data = ''

    if form.validate_on_submit():
        try:
            # Save the OpenAI key for the logged-in user
            openai_key = form.openai_key.data.strip()
            conn.execute('''
                UPDATE User
                SET openai_key = ?
                WHERE id = ?
            ''', (openai_key, current_user.id))

            # Save the sections
            for i, section in enumerate(SECTIONS):
                use_ai = form.sections[i].use_ai.data
                text_content = form.sections[i].text_content.data.strip()
                existing = conn.execute('SELECT id FROM GlobalGenerationSettings WHERE section = ?', (section,)).fetchone()
                if existing:
                    conn.execute('''
                        UPDATE GlobalGenerationSettings
                        SET use_ai = ?, text_content = ?
                        WHERE id = ?
                    ''', (use_ai, text_content, existing['id']))
                else:
                    conn.execute('''
                        INSERT INTO GlobalGenerationSettings (section, use_ai, text_content)
                        VALUES (?, ?, ?)
                    ''', (section, use_ai, text_content))
            conn.commit()
            flash('Paramètres globaux de génération mis à jour avec succès!', 'success')
            return redirect(url_for('settings.edit_global_generation_settings'))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de la mise à jour des paramètres : {e}', 'danger')
    else:
        if request.method == 'POST':
            # Debugging form validation errors
            for field_name, field in form._fields.items():
                if field.errors:
                    print(f"Erreurs dans le champ '{field_name}': {field.errors}")
            flash('Validation du formulaire échouée. Veuillez vérifier vos entrées.', 'danger')

    # Prepare the list of sections with their forms
    sections_with_forms = list(zip(form.sections, SECTIONS))
    conn.close()
    return render_template('edit_global_generation_settings.html', form=form, sections_with_forms=sections_with_forms)
