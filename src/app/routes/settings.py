from flask import Blueprint, request, render_template, flash, redirect, url_for, current_app, jsonify
from flask_login import login_required, current_user
from config.constants import SECTIONS  # Importer la liste des sections
from utils.decorator import role_required, roles_required
from app.forms import GlobalGenerationSettingsForm,  DeletePlanForm, UploadForm
from app.routes.evaluation import AISixLevelGridResponse
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import generate_csrf
import json
from pathlib import Path
from flask import send_from_directory, current_app
import os
from werkzeug.utils import secure_filename


csrf = CSRFProtect()


# Importez bien sûr db, User et GlobalGenerationSettings depuis vos modèles
from app.models import db, User, GlobalGenerationSettings, GrillePromptSettings, PlanDeCours, Cours, Programme, PlanDeCoursPromptSettings, AnalysePlanCoursPrompt

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

# Liste des canevas existants
CANEVAS_LIST = ['plan_cadre_template.docx', 'plan_de_cours_template.docx', 'evaluation_grid_template.docx']

@settings_bp.route('/analyse_prompt', methods=['GET', 'POST'])
@roles_required('admin')
@login_required 
def configure_analyse_prompt():
    if current_user.role != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))

    prompt = AnalysePlanCoursPrompt.query.first()
    if not prompt:
        default_template = """Tu es un assistant IA expert en évaluation de plans de cours dans l'enseignement supérieur. Ta mission principale est d'analyser la cohérence entre le calendrier du cours et les savoir-faire/compétences définis dans le plan-cadre.

FOCUS PRINCIPAL - ALIGNEMENT CALENDRIER ET SAVOIR-FAIRE (60 points) :
1. Analyse détaillée du calendrier (30 points)
   - Chaque semaine du calendrier doit être analysée en lien avec les savoir-faire
   - Évaluer si le temps alloué est suffisant pour chaque savoir-faire
   - Vérifier la progression logique des apprentissages

[... le reste de votre prompt actuel ...]

Voici les données du plan de cours (ID: {plan_cours_id}):
{plan_cours_json}

Voici les données du plan-cadre (ID: {plan_cadre_id}):
{plan_cadre_json}

Voici le schéma JSON auquel ta réponse doit strictement adhérer :
{schema_json}"""
        prompt = AnalysePlanCoursPrompt(prompt_template=default_template)
        db.session.add(prompt)
        db.session.commit()

    if request.method == 'POST':
        prompt.prompt_template = request.form.get('prompt_template')
        try:
            db.session.commit()
            flash('Prompt sauvegardé avec succès', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Erreur lors de la sauvegarde', 'error')
            logging.error(f"Erreur sauvegarde prompt: {e}")

    return render_template('settings/analyse_plan_cours_prompt.html', prompt=prompt)

@settings_bp.route('/gestion_canevas')
@roles_required('admin')
@login_required 
def gestion_canevas():
    form = UploadForm()
    return render_template('/settings/gestion_canevas.html', canevas_list=CANEVAS_LIST, upload_form=form)

@settings_bp.route('/upload_canevas/<filename>', methods=['POST'])
@roles_required('admin')
@login_required 
def upload_canevas(filename):
    if 'file' not in request.files:
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('settings.gestion_canevas'))

    file = request.files['file']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('settings.gestion_canevas'))

    if file:
        upload_folder = current_app.config['UPLOAD_FOLDER']
        existing_file_path = os.path.join(upload_folder, filename)

        # Vérifier si le fichier existe avant de le supprimer
        if os.path.exists(existing_file_path):
            os.remove(existing_file_path)

        # Sauvegarder le nouveau fichier avec le même nom que l'original
        file.save(os.path.join(upload_folder, filename))

        flash('Le canevas a été remplacé avec succès!', 'success')
        return redirect(url_for('settings.gestion_canevas'))

    flash('Une erreur s\'est produite lors du remplacement du canevas.', 'danger')
    return redirect(url_for('settings.gestion_canevas'))

@settings_bp.route('/download_canevas/<filename>')
@roles_required('admin')
@login_required 
def download_canevas(filename):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, filename)

    if not os.path.exists(file_path):
        current_app.logger.error(f"Fichier introuvable : {file_path}")
        flash('Le fichier demandé est introuvable.', 'danger')
        return redirect(url_for('settings.gestion_canevas'))

    return send_from_directory(upload_folder, filename, as_attachment=True)


@settings_bp.route('/plan-de-cours/prompts', methods=['GET'])
@roles_required('admin')
@login_required 
def plan_de_cours_prompt_settings():
    """Page de gestion des configurations de prompts pour les plans de cours."""
    prompts = PlanDeCoursPromptSettings.query.all()
    # Utiliser generate_csrf() au lieu de _get_token()
    return render_template(
        'settings/plan_de_cours_prompts.html',
        prompts=prompts
    )

@settings_bp.route('/plan-de-cours/prompts/<int:prompt_id>', methods=['PUT', 'POST'])
@roles_required('admin')
@login_required 
def update_plan_de_cours_prompt(prompt_id):
    """Met à jour une configuration de prompt pour plan de cours."""
    try:
        prompt = PlanDeCoursPromptSettings.query.get_or_404(prompt_id)
        
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        
        # Validation des données
        if not isinstance(data.get('prompt_template'), str):
            return jsonify({'error': 'prompt_template must be a string'}), 400
            
        if not isinstance(data.get('context_variables'), list):
            return jsonify({'error': 'context_variables must be a list'}), 400
        
        prompt.prompt_template = data['prompt_template']
        prompt.context_variables = data['context_variables']
        
        db.session.commit()
        return jsonify({'message': 'Configuration mise à jour avec succès'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@settings_bp.route('/plan-de-cours/prompts/test', methods=['POST'])
@roles_required('admin')
@login_required 
def test_plan_de_cours_prompt():
    """Teste un prompt de plan de cours avec des données exemple."""
    data = request.get_json()
    template = data.get('template')
    test_context = data.get('context', {})
    
    try:
        result = template.format(**test_context)
        return jsonify({'result': result})
    except KeyError as e:
        return jsonify({'error': f'Variable manquante: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400



@settings_bp.route('/parametres')
@login_required  # Cette route nécessite que l'utilisateur soit connecté
def parametres():
    return render_template('parametres.html')

@settings_bp.route("/gestion-plans-cours", methods=["GET"])
@roles_required('admin', 'coordo')
def gestion_plans_cours():
    form = DeletePlanForm()
    # Récupérer tous les plans de cours, avec leurs relations
    plans = (PlanDeCours.query
            .join(Cours)
            .join(Programme)
            .options(
                db.joinedload(PlanDeCours.cours),
                db.joinedload(PlanDeCours.cours).joinedload(Cours.programme)
            )
            .order_by(Programme.nom, Cours.code, PlanDeCours.session)
            .all())
    
    return render_template(
        "settings/gestion_plans_cours.html",
        plans=plans,
        active_page="gestion_plans_cours",
        form=form
    )

@settings_bp.route("/supprimer-plan-cours/<int:plan_id>", methods=["POST"])
@roles_required('admin', 'coordo')
def supprimer_plan_cours(plan_id):
    form = DeletePlanForm()
    print(f"Route de suppression appelée avec plan_id: {plan_id}")  # Debug
    # Afficher toutes les routes enregistrées
    print("Routes disponibles:")
    for rule in current_app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule}")
    if current_user.role not in ['admin', 'coordo']:
        flash("Vous n'avez pas les droits pour supprimer un plan de cours.", "error")
        return redirect(url_for('settings.gestion_plans_cours'))

    plan = db.session.get(PlanDeCours, plan_id)
    if not plan:
        flash("Plan de cours introuvable.", "error")
        return redirect(url_for('settings.gestion_plans_cours'))

    try:
        cours = plan.cours
        session = plan.session
        db.session.delete(plan)
        db.session.commit()
        flash(f"Le plan de cours {cours.code} - {session} a été supprimé avec succès.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression du plan de cours : {str(e)}", "error")

    return redirect(url_for('settings.gestion_plans_cours'))

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
