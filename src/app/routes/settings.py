from flask import Blueprint, request, render_template, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from config.constants import SECTIONS  # Importer la liste des sections
from utils.decorator import role_required, roles_required
from app.forms import GlobalGenerationSettingsForm
from app.routes.evaluation import AISixLevelGridResponse
from flask_wtf.csrf import CSRFProtect
import json

# Importez bien sûr db, User et GlobalGenerationSettings depuis vos modèles
from app.models import db, User, GlobalGenerationSettings, GrillePromptSettings

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

@settings_bp.route('/parametres')
@login_required  # Cette route nécessite que l'utilisateur soit connecté
def parametres():
    return render_template('parametres.html')

@settings_bp.route('/prompt-settings', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
def prompt_settings():
    settings = GrillePromptSettings.get_current()
    schema_json = json.dumps(AISixLevelGridResponse.get_schema_with_descriptions(), indent=4, ensure_ascii=False)
    
    if request.method == 'POST':
        try:
            settings.prompt_template = request.form.get('prompt_template')
            settings.level1_description = request.form.get('level1_description')
            settings.level2_description = request.form.get('level2_description')
            settings.level3_description = request.form.get('level3_description')
            settings.level4_description = request.form.get('level4_description')
            settings.level5_description = request.form.get('level5_description')
            settings.level6_description = request.form.get('level6_description')
            
            db.session.commit()
            flash('Paramètres mis à jour avec succès', 'success')
            return redirect(url_for('settings.prompt_settings'))
        except Exception as e:
            flash(f'Erreur lors de la mise à jour : {str(e)}', 'error')
            db.session.rollback()
    
    return render_template('settings/prompt_settings.html', 
                         settings=settings,
                         schema_json=schema_json)

@settings_bp.route('/generation', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
def edit_global_generation_settings():
    form = GlobalGenerationSettingsForm()

    if request.method == 'GET':
        # Récupérer la clé OpenAI de l'utilisateur connecté via SQLAlchemy
        user = User.query.get(current_user.id)
        if user:
            form.openai_key.data = user.openai_key

        # Vérifier la cohérence entre le formulaire et le nombre de SECTIONS
        current_entries = len(form.sections)
        required_entries = len(SECTIONS)
        if current_entries < required_entries:
            for _ in range(required_entries - current_entries):
                form.sections.append_entry()
        elif current_entries > required_entries:
            for _ in range(current_entries - required_entries):
                form.sections.pop_entry()

        # Charger les réglages existants
        settings = GlobalGenerationSettings.query.all()

        for i, section in enumerate(SECTIONS):
            setting = next((s for s in settings if s.section == section), None)
            if setting:
                form.sections[i].use_ai.data = bool(setting.use_ai)
                form.sections[i].text_content.data = setting.text_content
            else:
                form.sections[i].use_ai.data = False
                form.sections[i].text_content.data = ''

    if form.validate_on_submit():
        try:
            # Mettre à jour (ou créer) les entrées GlobalGenerationSettings
            for i, section in enumerate(SECTIONS):
                use_ai = form.sections[i].use_ai.data
                text_content = form.sections[i].text_content.data.strip()

                existing_setting = GlobalGenerationSettings.query.filter_by(section=section).first()
                if existing_setting:
                    existing_setting.use_ai = use_ai
                    existing_setting.text_content = text_content
                else:
                    new_setting = GlobalGenerationSettings(
                        section=section,
                        use_ai=use_ai,
                        text_content=text_content
                    )
                    db.session.add(new_setting)

            db.session.commit()
            flash('Paramètres globaux de génération mis à jour avec succès!', 'success')
            return redirect(url_for('settings.edit_global_generation_settings'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour des paramètres : {e}', 'danger')

    else:
        if request.method == 'POST':
            # Debugging form validation errors
            for field_name, field in form._fields.items():
                if field.errors:
                    print(f"Erreurs dans le champ '{field_name}': {field.errors}")
            flash('Validation du formulaire échouée. Veuillez vérifier vos entrées.', 'danger')

    # Préparer la liste des sections pour le rendu
    sections_with_forms = list(zip(form.sections, SECTIONS))
    return render_template('edit_global_generation_settings.html', form=form, sections_with_forms=sections_with_forms)
