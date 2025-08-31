import json
import os

from flask import Blueprint, request, render_template, flash, redirect, url_for, jsonify
from flask import send_from_directory, current_app
from flask_login import login_required, current_user
from flask_wtf.csrf import CSRFProtect

from ..forms import (
    DeletePlanForm,
    UploadForm,
    ProfileEditForm,
    AnalysePromptForm,
    PlanDeCoursPromptSettingsForm,
    OpenAIModelForm,
    ChatSettingsForm,
    SectionAISettingsForm,
    APITokenForm,
    OcrPromptSettingsForm,
    PlanCadreImportPromptSettingsForm,
)
from .evaluation import AISixLevelGridResponse
from ...utils.decorator import role_required, roles_required, ensure_profile_completed

csrf = CSRFProtect()


# Importez bien sûr db et User depuis vos modèles
from ..models import (
    db,
    User,
    GrillePromptSettings,
    PlanDeCours,
    Cours,
    Programme,
    PlanDeCoursPromptSettings,
    AnalysePlanCoursPrompt,
    ListeCegep,
    Department,
    OpenAIModel,
    ChatModelConfig,
    SectionAISettings,
    OcrPromptSettings,
    PlanCadreImportPromptSettings,
)

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

# Liste des canevas existants
CANEVAS_LIST = ['plan_cadre_template.docx', 'plan_de_cours_template.docx', 'evaluation_grid_template.docx']


@settings_bp.route('/openai_models', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_openai_models():
    """Page de gestion des modèles OpenAI."""
    form = OpenAIModelForm()
    models = OpenAIModel.query.all()
    
    if form.validate_on_submit():
        # Vérifier si le modèle existe déjà
        existing = OpenAIModel.query.filter_by(name=form.name.data.strip()).first()
        if existing:
            flash("Ce modèle existe déjà.", "warning")
        else:
            new_model = OpenAIModel(
                name=form.name.data.strip(),
                input_price=float(form.input_price.data),
                output_price=float(form.output_price.data)
            )
            db.session.add(new_model)
            db.session.commit()
            flash("Modèle ajouté avec succès.", "success")
        return redirect(url_for('settings.manage_openai_models'))

    return render_template('settings/manage_openai_models.html', models=models, form=form)


@settings_bp.route('/ocr_prompts', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ocr_prompt_settings():
    """Configuration des prompts et modèles pour l'extraction de compétences (devis ministériels)."""
    settings = OcrPromptSettings.get_current()
    form = OcrPromptSettingsForm(obj=settings)
    # Section-level IA params (reasoning/verbosity) are configured here (prompt système OCR reste dans OcrPromptSettings)
    sa = SectionAISettings.get_for('ocr')
    ai_form = SectionAISettingsForm(obj=sa)

    # Pré-remplir un prompt d'extraction par défaut pour affichage si vide
    if request.method == 'GET' and not (settings and (settings.extraction_prompt or '').strip()):
        default_extraction = (
            "Assistant d'extraction OCR: identifie chaque compétence (code, nom), extrait le Contexte de réalisation (listes hiérarchiques), "
            "les Critères de performance et les Éléments avec leurs critères. Retourne un JSON strict 'competences' conforme au schéma affiché."
        )
        form.extraction_prompt.data = default_extraction

    if form.validate_on_submit():
        if settings is None:
            settings = OcrPromptSettings()
            db.session.add(settings)
        # On ne conserve désormais qu'un seul prompt système (extraction)
        settings.extraction_prompt = form.extraction_prompt.data or None
        # Un seul modèle pertinent: celui d'extraction
        settings.model_extraction = form.model_extraction.data or None
        try:
            # Mettre à jour aussi les paramètres IA (raisonnement/verbosité) sans toucher au prompt système (géré ci-dessus)
            ai_form = SectionAISettingsForm(formdata=request.form, obj=sa)
            if ai_form.validate():
                sa.reasoning_effort = ai_form.reasoning_effort.data or None
                sa.verbosity = ai_form.verbosity.data or None
            db.session.commit()
            flash('Paramètres OCR (prompts IA) enregistrés.', 'success')
            return redirect(url_for('settings.ocr_prompt_settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur enregistrement OcrPromptSettings: {e}")
            flash("Erreur lors de l'enregistrement.", 'danger')

    return render_template('settings/ocr_prompt_settings.html', form=form, ai_form=ai_form)


@settings_bp.route('/plan-cadre/import_prompt', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def plan_cadre_import_prompt_settings():
    """Configuration du prompt système pour l'import DOCX du plan-cadre."""
    settings = PlanCadreImportPromptSettings.get_current()
    form = PlanCadreImportPromptSettingsForm(obj=settings)

    if form.validate_on_submit():
        if settings is None:
            settings = PlanCadreImportPromptSettings()
            db.session.add(settings)
        settings.prompt_template = form.prompt_template.data
        settings.ai_model = form.ai_model.data
        try:
            db.session.commit()
            flash('Paramètres d\'import Plan‑cadre enregistrés.', 'success')
            return redirect(url_for('settings.plan_cadre_import_prompt_settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur enregistrement PlanCadreImportPromptSettings: {e}")
            flash("Erreur lors de l'enregistrement.", 'danger')

    return render_template('settings/plan_cadre_import_prompt.html', form=form)

@settings_bp.route('/openai_models/delete/<int:model_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_openai_model(model_id):
    """Supprime un modèle OpenAI."""
    model = db.session.get(OpenAIModel, model_id)
    if model:
        db.session.delete(model)
        db.session.commit()
        flash("Modèle supprimé avec succès.", "success")
    else:
        flash("Modèle introuvable.", "danger")
    return redirect(url_for('settings.manage_openai_models'))


@settings_bp.route('/chat_models', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def chat_model_settings():
    """Configure les paramètres des modèles pour le chat."""
    config = ChatModelConfig.get_current()
    form = ChatSettingsForm(obj=config)

    if form.validate_on_submit():
        config.chat_model = form.chat_model.data
        # Nouveau fonctionnement: tool_model = chat_model (toujours le même modèle)
        config.tool_model = config.chat_model
        config.reasoning_effort = form.reasoning_effort.data
        config.verbosity = form.verbosity.data
        db.session.commit()
        flash('Paramètres du chat mis à jour.', 'success')
        return redirect(url_for('settings.chat_model_settings'))
    # Assurer l'affichage cohérent: refléter le couplage côté formulaire
    form.tool_model.data = config.chat_model
    return render_template('settings/chat_models.html', form=form)


def _edit_section_ai_settings(section_key: str, title: str, description: str):
    settings = SectionAISettings.get_for(section_key)
    form = SectionAISettingsForm(obj=settings)
    if form.validate_on_submit():
        settings.system_prompt = form.system_prompt.data or None
        settings.ai_model = form.ai_model.data or None
        settings.reasoning_effort = form.reasoning_effort.data or None
        settings.verbosity = form.verbosity.data or None
        try:
            db.session.commit()
            flash('Paramètres IA enregistrés.', 'success')
            return redirect(request.path)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur SectionAISettings save ({section_key}): {e}")
            flash("Erreur lors de l'enregistrement.", 'danger')
    return render_template('settings/section_ai_settings.html', form=form, title=title, description=description)


@settings_bp.route('/plan-de-cours/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_de_cours_settings():
    # Prefill default for display if empty
    s = SectionAISettings.get_for('plan_de_cours')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Tu es un assistant pédagogique qui génère des plans de cours en français. "
            "Respecte le ton institutionnel, la clarté et la concision. Appuie‑toi sur les données disponibles, "
            "n'invente pas d'informations. Lorsque tu dois structurer, respecte le schéma demandé."
        )
    return _edit_section_ai_settings(
        'plan_de_cours',
        'Plans de cours – Paramètres IA',
        "Configurez le prompt système, le modèle, le niveau de raisonnement et la verbosité pour les tâches IA liées aux plans de cours (génération, amélioration, calendrier, évaluations)."
    )


@settings_bp.route('/plan-de-cours/ai-improve', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_de_cours_improve_settings():
    s = SectionAISettings.get_for('plan_de_cours_improve')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Tu es un assistant qui améliore un plan de cours existant en français. "
            "Améliore la lisibilité et la précision sans changer le sens ni inventer. "
            "Préserve la structure et le vocabulaire institutionnel; corrige la langue et uniformise le style."
        )
    return _edit_section_ai_settings(
        'plan_de_cours_improve',
        'Plans de cours – Paramètres IA (Amélioration)',
        "Configurez un prompt système spécifique pour les actions d'amélioration des champs du plan de cours."
    )


@settings_bp.route('/plan-de-cours/ai-import', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_de_cours_import_settings():
    # Pré-remplir un prompt d'importation par défaut (affichage) si vide
    s = SectionAISettings.get_for('plan_de_cours_import')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Assistant d'importation de plan de cours: le texte peut contenir des tableaux Markdown (‘TABLE n:’ … ‘ENDTABLE’) "
            "qui prévalent sur le texte libre. Retourne une sortie STRICTEMENT conforme au schéma attendu (Pydantic côté serveur). "
            "Règles spécifiques: \n"
            "- Les tableaux calendrier (Semaine, Sujet, Activités, Travaux hors classe, Évaluations) → map vers 'calendriers'.\n"
            "- Les tableaux d’évaluations (Titre, Description, Semaine, pondérations par Capacité) → map vers 'evaluations' et 'capacites' (capacite, ponderation).\n"
            "- N'invente pas; conserve fidèlement le contenu; valeurs null si absentes."
        )
    return _edit_section_ai_settings(
        'plan_de_cours_import',
        'Plans de cours – Paramètres IA (Importation)',
        "Configurez un prompt système spécifique pour l'importation d'un plan de cours (DOCX→BD)."
    )


@settings_bp.route('/plan-cadre/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_cadre_settings():
    return _edit_section_ai_settings(
        'plan_cadre',
        'Plan‑cadre – Paramètres IA',
        "Paramètres IA pour la génération/amélioration du plan‑cadre."
    )


@settings_bp.route('/plan-cadre/ai-improve', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_cadre_improve_settings():
    return _edit_section_ai_settings(
        'plan_cadre_improve',
        'Plan‑cadre – Paramètres IA (Amélioration)',
        "Configurez un prompt système spécifique pour les actions d'amélioration du plan‑cadre."
    )


@settings_bp.route('/plan-cadre/ai-import', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_plan_cadre_import_settings():
    return _edit_section_ai_settings(
        'plan_cadre_import',
        'Plan‑cadre – Paramètres IA (Importation)',
        "Configurez un prompt système spécifique pour l'importation du plan‑cadre (DOCX→BD)."
    )


@settings_bp.route('/plan-cadre/prompts', methods=['GET'])
@login_required
@role_required('admin')
def plan_cadre_prompts():
    """Page de configuration des prompts IA pour Plan‑cadre (génération/amélioration/importation)."""
    from ..models import SectionAISettings
    sa_gen = SectionAISettings.get_for('plan_cadre')
    sa_impv = SectionAISettings.get_for('plan_cadre_improve')
    sa_impt = SectionAISettings.get_for('plan_cadre_import')

    # Defaults non persistés (uniquement pour affichage si vide)
    default_gen = (
        "Tu es un assistant pédagogique qui génère des contenus de plan‑cadre en français. "
        "Respecte le ton institutionnel, la clarté et la concision. Appuie‑toi sur les données existantes, "
        "n'invente pas d'informations. Lorsque tu dois structurer, respecte le schéma demandé."
    )
    default_impv = (
        "Tu es un assistant qui améliore un plan‑cadre existant en français. "
        "Améliore la lisibilité et la précision sans changer le sens ni inventer. "
        "Préserve la structure et le vocabulaire institutionnel; corrige la langue et uniformise le style."
    )
    default_impt = (
        "Tu es un assistant d'importation. Analyse un plan‑cadre (texte brut/fiche) et renvoie une sortie strictement conforme au schéma. "
        "Le contenu des tableaux prévaut sur le texte s'il y a conflit. Mets null lorsqu'une information est absente."
    )

    if not (sa_gen.system_prompt or '').strip():
        sa_gen.system_prompt = default_gen
    if not (sa_impv.system_prompt or '').strip():
        sa_impv.system_prompt = default_impv
    if not (sa_impt.system_prompt or '').strip():
        sa_impt.system_prompt = default_impt

    ai_form_gen = SectionAISettingsForm(obj=sa_gen)
    ai_form_impv = SectionAISettingsForm(obj=sa_impv)
    ai_form_impt = SectionAISettingsForm(obj=sa_impt)

    return render_template(
        'settings/plan_cadre_prompts.html',
        ai_form_gen=ai_form_gen,
        ai_form_impv=ai_form_impv,
        ai_form_impt=ai_form_impt,
    )


@settings_bp.route('/logigramme/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_logigramme_settings():
    s = SectionAISettings.get_for('logigramme')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "À partir des cours et des compétences fournis (données JSON), déduis les liens cours→compétence avec un type parmi "
            "'developpe', 'atteint', 'reinvesti'. Retourne strictement un JSON {\"links\": [{\"cours_code\": str, \"competence_code\": str, \"type\": str}]} sans texte hors JSON."
        )
    return _edit_section_ai_settings(
        'logigramme',
        'Logigramme – Paramètres IA',
        "Paramètres IA pour la génération de logigrammes compétences."
    )


@settings_bp.route('/grille/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_grille_settings():
    s = SectionAISettings.get_for('grille')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Tu es un conseiller pédagogique. À partir des contraintes (heures totales, nombre de sessions, unités) et de la liste des compétences, "
            "propose une grille de cours par session. Retourne un JSON strict avec 'sessions' (liste de {session, courses}) "
            "où chaque cours contient 'nom', 'heures_theorie', 'heures_laboratoire', 'heures_travail_maison', 'nombre_unites', 'prealables', 'corequis'."
        )
    return _edit_section_ai_settings(
        'grille',
        'Grille de cours – Paramètres IA',
        "Paramètres IA pour la génération de grilles par session."
    )


@settings_bp.route('/ocr/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_ocr_settings():
    return _edit_section_ai_settings(
        'ocr',
        'Devis ministériels (OCR) – Paramètres IA',
        "Paramètres IA pour l'extraction/segmentation des compétences depuis un devis PDF."
    )


@settings_bp.route('/chat/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_chat_settings():
    s = SectionAISettings.get_for('chat')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Vous êtes EDxo, un assistant IA spécialisé dans les plans de cours et plans‑cadres. Répondez de manière concise et professionnelle en français."
        )
    return _edit_section_ai_settings(
        'chat',
        'Chat IA – Paramètres IA',
        "Paramètres IA pour les conversations (SSE, outils)."
    )

@settings_bp.route('/grille/ai-import', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_grille_import_settings():
    s = SectionAISettings.get_for('grille_import')
    if not (s.system_prompt or '').strip():
        s.system_prompt = (
            "Assistant d’importation de grille: à partir d’un PDF, extrais uniquement la formation spécifique et construis un JSON strictement conforme "
            "au schéma 'programme_etudes' (sessions, cours avec pondérations X‑Y‑Z → théorie/labo/maison, préalables/corequis). Aucune invention."
        )
    return _edit_section_ai_settings(
        'grille_import',
        'Grille de cours – Paramètres IA (Importation)',
        "Configurez le prompt système dédié à l'importation de grilles de cours depuis PDF."
    )


@settings_bp.route('/evaluation/ai', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def ai_evaluation_settings():
    return _edit_section_ai_settings(
        'evaluation',
        "Grille d'évaluation – Paramètres IA",
        "Paramètres IA pour la génération de grilles d'évaluation à 6 niveaux."
    )


@settings_bp.route('/grille', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def grille_settings():
    """Paramètres pour la Grille de cours: génération et importation."""
    sa_gen = SectionAISettings.get_for('grille')
    sa_imp = SectionAISettings.get_for('grille_import')
    # Defaults for display (not persisted unless saved)
    default_gen = (
        "Conseiller pédagogique – Génération de grille:\n"
        "- Respecte strictement un JSON: {sessions:[{session:int,courses:[{nom,heures_theorie,heures_laboratoire,heures_travail_maison,nombre_unites,prealables,corequis}]}],fils_conducteurs:[{description,couleur,cours}]}\n"
        "- Calcule nombre_unites = (heures_theorie + heures_laboratoire + heures_travail_maison)/3.\n"
        "- h_cours = (heures_theorie + heures_laboratoire) * 15; somme(h_cours) sur TOUTES les sessions = Heures totales à répartir (égalité stricte).\n"
        "- Si des unités totales sont fournies: somme(nombre_unites) = Unités totales (égalité stricte).\n"
        "- Répartis heures/unités de façon équilibrée et cohérente avec les compétences.\n"
        "- prealables: max 2 par cours, seulement vers des cours en sessions antérieures.\n"
        "- corequis: cours de la même session uniquement. Limiter le nombre global de liens au strict nécessaire.\n"
        "- Génère 3–6 fils_conducteurs (description courte, couleur hex unique, cours[]); chaque cours ∈ 0..1 fil.\n"
        "- N'invente pas de données; utilise uniquement le contexte fourni."
    )
    default_imp = (
        "Tu es un assistant d'importation de grille de cours. À partir d'un PDF, extrais uniquement la formation spécifique "
        "et renvoie un JSON strictement conforme au schéma fourni. Ne crée pas de données, et respecte les pondérations X-Y-Z."
    )
    if not (sa_gen.system_prompt or '').strip():
        sa_gen.system_prompt = default_gen
    if not (sa_imp.system_prompt or '').strip():
        sa_imp.system_prompt = default_imp
    form_gen = SectionAISettingsForm(obj=sa_gen, prefix='gen')
    form_imp = SectionAISettingsForm(obj=sa_imp, prefix='imp')

    if request.method == 'POST':
        form_gen = SectionAISettingsForm(formdata=request.form, obj=sa_gen, prefix='gen')
        form_imp = SectionAISettingsForm(formdata=request.form, obj=sa_imp, prefix='imp')
        ok = True
        if form_gen.validate():
            sa_gen.system_prompt = form_gen.system_prompt.data or None
            sa_gen.ai_model = form_gen.ai_model.data or None
            sa_gen.reasoning_effort = form_gen.reasoning_effort.data or None
            sa_gen.verbosity = form_gen.verbosity.data or None
        else:
            ok = False
        if form_imp.validate():
            sa_imp.system_prompt = form_imp.system_prompt.data or None
            sa_imp.ai_model = form_imp.ai_model.data or None
            sa_imp.reasoning_effort = form_imp.reasoning_effort.data or None
            sa_imp.verbosity = form_imp.verbosity.data or None
        else:
            ok = False
        if ok:
            try:
                db.session.commit()
                flash('Paramètres Grille de cours enregistrés.', 'success')
                return redirect(url_for('settings.grille_settings'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Erreur enregistrement grille settings: {e}")
                flash("Erreur lors de l'enregistrement.", 'danger')
        else:
            flash('Validation du formulaire échouée. Veuillez vérifier vos entrées.', 'danger')

    return render_template('settings/grille_settings.html', form_gen=form_gen, form_imp=form_imp)


## Route '/settings/generation' supprimée (ancien paramétrage global)


@settings_bp.route('/developer', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def developer():
    form = APITokenForm()
    if form.validate_on_submit():
        days = form.ttl.data or 30
        current_user.generate_api_token(expires_in=days * 24 * 3600)
        flash('Jeton API généré.', 'success')
        return redirect(url_for('settings.developer'))
    return render_template(
        'settings/developer.html',
        form=form,
        token=current_user.api_token,
        expires_at=current_user.api_token_expires_at,
    )

@settings_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def edit_profile():
    form = ProfileEditForm()
    
    # Charger les données
    all_cegeps = ListeCegep.query.all()
    all_departments = Department.query.all()
    all_programmes = Programme.query.all()
    
    form.cegep.choices = [(c.id, c.nom) for c in all_cegeps]
    form.department.choices = [(d.id, d.nom) for d in all_departments]
    
    # Définir les choix pour les programmes
    form.programmes.choices = [(p.id, p.nom) for p in all_programmes]
    
    # Configuration de l'avatar
    seed = current_user.email or str(current_user.id)
    dicebear_styles = ["pixel-art", "bottts", "adventurer", "lorelei", "identicon"]
    avatar_choices = [(f"https://api.dicebear.com/7.x/{style}/svg?seed={seed}&backgroundColor=b6e3f4", 
                      style.capitalize()) for style in dicebear_styles]
    form.image.choices = avatar_choices
    avatar_url = current_user.image or avatar_choices[0][0]

    if request.method == 'POST':
        # Débogage
        print("Form data:", request.form)
        print("Form errors:", form.errors)
        
        if form.validate_on_submit():
            try:
                # Mettre à jour les données de l'utilisateur
                current_user.nom = form.nom.data
                current_user.prenom = form.prenom.data
                current_user.email = form.email.data
                current_user.image = form.image.data
                current_user.cegep_id = form.cegep.data
                current_user.department_id = form.department.data
                
                # Gérer les programmes
                selected_ids = form.programmes.data
                current_user.programmes = [
                    db.session.get(Programme, int(pid)) 
                    for pid in selected_ids 
                    if db.session.get(Programme, int(pid))
                ]
                
                db.session.commit()
                flash('Profil mis à jour avec succès', 'success')
                return redirect(url_for('settings.edit_profile'))
                
            except Exception as e:
                db.session.rollback()
                print("Database error:", str(e))
                flash('Erreur lors de la mise à jour', 'danger')
    else:
        # Remplir le formulaire avec les données actuelles
        form.nom.data = current_user.nom
        form.prenom.data = current_user.prenom
        form.email.data = current_user.email
        form.cegep.data = current_user.cegep_id
        form.department.data = current_user.department_id
        form.image.data = avatar_url
        form.programmes.data = [p.id for p in current_user.programmes]
    
    return render_template('settings/edit_profile.html',
                           form=form,
                           avatar_url=avatar_url,
                           programmes=all_programmes)



@settings_bp.route('/get_departments/<int:cegep_id>', methods=['GET'])
@login_required
@ensure_profile_completed
def get_departments(cegep_id):
    """Retourne la liste des départements en JSON pour un cégep donné."""
    departments = Department.query.filter_by(cegep_id=cegep_id).all()
    data = [[d.id, d.nom] for d in departments]
    return jsonify(data)

@settings_bp.route('/get_programmes/<int:dept_id>', methods=['GET'])
@login_required
@ensure_profile_completed
def get_programmes(dept_id):
    """Retourne la liste des programmes en JSON pour un département donné."""
    programmes = Programme.query.filter_by(department_id=dept_id).all()
    data = [[p.id, p.nom] for p in programmes]
    return jsonify(data)

@settings_bp.route('/analyse_prompt', methods=['GET', 'POST'])
@roles_required('admin')
@login_required 
@ensure_profile_completed
def configure_analyse_prompt():
    if current_user.role != 'admin':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))

    prompt = AnalysePlanCoursPrompt.query.first()
    if not prompt:
        default_template = """Tu es un assistant IA expert en évaluation de plans de cours dans l'enseignement supérieur. Ta mission principale est d'analyser la cohérence entre le calendrier du cours et les savoir-faire/compétences définis dans le plan-cadre.

[... votre prompt par défaut ...]"""
        prompt = AnalysePlanCoursPrompt(prompt_template=default_template)
        db.session.add(prompt)
        db.session.commit()

    form = AnalysePromptForm(obj=prompt)
    sa = SectionAISettings.get_for('analyse_plan_cours')
    ai_form = SectionAISettingsForm(obj=sa)

    if form.validate_on_submit():
        form.populate_obj(prompt)
        try:
            # Persister aussi les paramètres IA de la section
            ai_form = SectionAISettingsForm(formdata=request.form, obj=sa)
            if ai_form.validate():
                # Ne mettre à jour le prompt système que s'il est soumis (évite d'effacer en l'absence du champ)
                if 'system_prompt' in request.form:
                    sa.system_prompt = ai_form.system_prompt.data or None
                sa.reasoning_effort = ai_form.reasoning_effort.data or None
                sa.verbosity = ai_form.verbosity.data or None
            db.session.commit()
            flash('Prompt, modèle et paramètres IA sauvegardés', 'success')
            return redirect(url_for('settings.configure_analyse_prompt'))
        except Exception as e:
            db.session.rollback()
            flash('Erreur lors de la sauvegarde', 'error')
            current_app.logger.error(f"Erreur sauvegarde prompt: {e}")

    return render_template('settings/analyse_plan_cours_prompt.html', form=form, ai_form=ai_form)

@settings_bp.route('/gestion_canevas')
@roles_required('admin')
@login_required
@ensure_profile_completed
def gestion_canevas():
    form = UploadForm()
    return render_template('/settings/gestion_canevas.html', canevas_list=CANEVAS_LIST, upload_form=form)

@settings_bp.route('/upload_canevas/<filename>', methods=['POST'])
@roles_required('admin')
@login_required 
@ensure_profile_completed
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
@ensure_profile_completed
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
@ensure_profile_completed
def plan_de_cours_prompt_settings():
    """Page de gestion des prompts Plan de cours.

    - Trois formulaires: Génération, Amélioration, Importation (prompts système distincts).
    - La configuration granulaire par champ a été retirée; tout est désormais couvert par le prompt système.
    """
    prompts = PlanDeCoursPromptSettings.query.all()

    # 3 configs IA: génération / amélioration / importation
    sa_gen = SectionAISettings.get_for('plan_de_cours')
    sa_impv = SectionAISettings.get_for('plan_de_cours_improve')
    sa_impt = SectionAISettings.get_for('plan_de_cours_import')

    # Defaults (affichés si vide pour guider l'admin)
    default_gen = (
        "Tu es un assistant pédagogique qui génère des plans de cours en français. "
        "Respecte le ton institutionnel, la clarté et la concision. Appuie-toi sur les données du plan-cadre, "
        "n'invente pas d'informations. Lorsque tu dois structurer une sortie, respecte le schéma demandé."
    )
    default_impv = (
        "Tu es un assistant qui améliore un plan de cours existant en français. "
        "Améliore la lisibilité et la précision sans changer le sens ni inventer. "
        "Préserve la structure et le vocabulaire institutionnel; corrige la langue et uniformise le style."
    )
    default_impt = (
        "Tu es un assistant d'importation. Analyse un plan de cours (texte brut) et renvoie une sortie strictement conforme au schéma. "
        "Le contenu des tableaux (calendrier/évaluations) prévaut sur le texte s'il y a conflit. Mets null lorsqu'une information est absente."
    )

    if not (sa_gen.system_prompt or '').strip():
        sa_gen.system_prompt = default_gen
    if not (sa_impv.system_prompt or '').strip():
        sa_impv.system_prompt = default_impv
    if not (sa_impt.system_prompt or '').strip():
        sa_impt.system_prompt = default_impt

    ai_form_gen = SectionAISettingsForm(obj=sa_gen)
    ai_form_impv = SectionAISettingsForm(obj=sa_impv)
    ai_form_impt = SectionAISettingsForm(obj=sa_impt)

    return render_template(
        'settings/plan_de_cours_prompts.html',
        prompts=prompts,
        ai_form_gen=ai_form_gen,
        ai_form_impv=ai_form_impv,
        ai_form_impt=ai_form_impt,
    )

@settings_bp.route('/plan-de-cours/prompts/<int:prompt_id>', methods=['POST'])
@roles_required('admin')
@login_required 
@ensure_profile_completed
def update_plan_de_cours_prompt(prompt_id):
    """Met à jour une configuration de prompt pour plan de cours."""
    try:
        prompt = db.session.get(PlanDeCoursPromptSettings, prompt_id) or abort(404)
        
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        
        # Validation des données
        if not isinstance(data.get('prompt_template'), str):
            return jsonify({'error': 'prompt_template must be a string'}), 400
        
        prompt.prompt_template = data['prompt_template']
        
        db.session.commit()
        return jsonify({'message': 'Configuration mise à jour avec succès'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@settings_bp.route('/plan-de-cours/prompts/test', methods=['POST'])
@roles_required('admin')
@login_required 
@ensure_profile_completed
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



@settings_bp.route('/plan-de-cours/prompt/<int:prompt_id>/edit', methods=['GET', 'POST'])
@roles_required('admin')
@login_required
@ensure_profile_completed
def edit_plan_de_cours_prompt(prompt_id):
    """Affiche et met à jour la configuration d'un prompt de plan de cours."""
    prompt = db.session.get(PlanDeCoursPromptSettings, prompt_id) or abort(404)
    form = PlanDeCoursPromptSettingsForm(obj=prompt)

    if form.validate_on_submit():
        form.populate_obj(prompt)
        try:
            db.session.commit()
            flash('Configuration sauvegardée avec succès', 'success')
            return redirect(url_for('settings.edit_plan_de_cours_prompt', prompt_id=prompt.id))
        except Exception as e:  # pylint: disable=broad-except
            db.session.rollback()
            flash('Erreur lors de la sauvegarde', 'error')
            current_app.logger.error(f"Erreur sauvegarde prompt: {e}")

    return render_template('settings/edit_plan_de_cours_prompt.html', form=form, prompt=prompt)


@settings_bp.route('/parametres')
@login_required  # Cette route nécessite que l'utilisateur soit connecté
@ensure_profile_completed
def parametres():
    return render_template('parametres.html')

@settings_bp.route("/gestion-plans-cours", methods=["GET"])
@roles_required('admin', 'coordo')
@ensure_profile_completed
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
@ensure_profile_completed
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
@ensure_profile_completed
def prompt_settings():
    """Paramétrage de la Grille d'évaluation + paramètres IA de la section 'evaluation'."""
    settings = GrillePromptSettings.get_current()
    sa = SectionAISettings.get_for('evaluation')
    ai_form = SectionAISettingsForm(obj=sa)

    if request.method == 'POST':
        try:
            # 1) Mettre à jour la Grille
            settings.prompt_template = request.form.get('prompt_template')

            # Copier le template comme prompt système de la section 'evaluation'
            # afin qu'il soit utilisé comme prompt système effectif.
            if settings.prompt_template:
                sa.system_prompt = settings.prompt_template

            # 2) Mettre à jour la config IA de section
            ai_form = SectionAISettingsForm(formdata=request.form, obj=sa)
            if ai_form.validate():
                # Système: mettre à jour uniquement si le champ est présent dans la requête
                if 'system_prompt' in request.form:
                    sa.system_prompt = ai_form.system_prompt.data or None
                sa.ai_model = ai_form.ai_model.data or None
                sa.reasoning_effort = ai_form.reasoning_effort.data or None
                sa.verbosity = ai_form.verbosity.data or None

            db.session.commit()
            flash('Paramètres mis à jour avec succès', 'success')
            return redirect(url_for('settings.prompt_settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {str(e)}', 'error')

    return render_template('settings/prompt_settings.html', settings=settings, ai_form=ai_form)


@settings_bp.route('/docx_to_schema_prompts', methods=['GET'])
@login_required
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_prompt_settings():
    """Page de configuration des prompts système pour la conversion DOCX→JSON."""
    return render_template('settings/docx_to_schema_prompts.html')
