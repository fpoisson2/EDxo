# routes/evaluation.py

import io
import json
import os
from functools import wraps
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    send_file,
    current_app
)
from flask_login import login_required, current_user
from openai import OpenAI
from openai import OpenAIError
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..forms import (
    CourseSelectionForm,
    PlanSelectionForm,
    EvaluationGridForm,
    EvaluationSelectionForm,
    SixLevelGridForm
)
from ..models import (
    db,
    Cours,
    PlanDeCours,
    PlanDeCoursEvaluations,
    PlanCadreCapacites,
    PlanCadre,
    PlanDeCoursEvaluationsCapacites,
    EvaluationSavoirFaire,
    PlanCadreCapaciteSavoirsFaire,
    GrillePromptSettings,
    User
)
from utils.decorator import roles_required, ensure_profile_completed
from utils.openai_pricing import calculate_call_cost


class AISixLevelGridResponse(BaseModel):
    """
    Représente la réponse structurée d'OpenAI pour une grille à six niveaux.
    """
    level1_description: Optional[str] = Field(
        None,
        description="Niveau 1 - Aucun travail réalisé"
    )
    level2_description: Optional[str] = Field(
        None,
        description="Niveau 2 - Performance très insuffisante"
    )
    level3_description: Optional[str] = Field(
        None,
        description="Niveau 3 - Performance insuffisante"
    )
    level4_description: Optional[str] = Field(
        None,
        description="Niveau 4 - Seuil de réussite minimal"
    )
    level5_description: Optional[str] = Field(
        None,
        description="Niveau 5 - Performance supérieure"
    )
    level6_description: Optional[str] = Field(
        None,
        description="Niveau 6 - Cible visée atteinte"
    )

    @classmethod
    def get_schema_with_descriptions(cls):
        """
        Met à jour le schéma avec les descriptions de la base de données
        """
        settings = GrillePromptSettings.get_current()
        schema = cls.model_json_schema()
        for i in range(1, 7):
            field_name = f'level{i}_description'
            schema['properties'][field_name]['description'] = getattr(settings, field_name)
        return schema

evaluation_bp = Blueprint('evaluation', __name__, url_prefix='/evaluation')

def admin_required(f):
    @wraps(f)
    @login_required
    @roles_required('admin')
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function

@evaluation_bp.route('/get_description/<int:evaluation_id>', methods=['GET'])
@login_required
@ensure_profile_completed
def get_description(evaluation_id):
    try:
        evaluation = PlanDeCoursEvaluations.query.get_or_404(evaluation_id)
        return jsonify({
            'success': True,
            'description': evaluation.description or ''
        })
    except Exception as e:
        current_app.logger.error(f'Erreur lors de la récupération de la description: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@evaluation_bp.route('/get_courses', methods=['GET'])
@login_required
@ensure_profile_completed
def get_courses():
    user_program_ids = [programme.id for programme in current_user.programmes]
    courses = Cours.query.filter(Cours.programme_id.in_(user_program_ids)).all()

    courses_data = [{
        'id': str(course.id),
        'code': course.code,
        'nom': course.nom
    } for course in courses]
    return jsonify(courses_data)




@login_required
@ensure_profile_completed
def create_evaluation_grid():
    # Étape 1 : Sélection du Cours
    course_form = CourseSelectionForm()
    course_form.course.choices = [(course.id, f"{course.code} - {course.nom}") for course in Cours.query.all()]
    
    if 'submit_course' in request.form and course_form.validate_on_submit():
        selected_course_id = course_form.course.data
        return redirect(url_for('evaluation.select_plan', course_id=selected_course_id))
    
    return render_template('evaluation/select_course.html', form=course_form)

@evaluation_bp.route('/select_plan/<int:course_id>', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def select_plan(course_id):
    plan_form = PlanSelectionForm()
    plans = PlanDeCours.query.filter_by(cours_id=course_id).order_by(PlanDeCours.session.desc()).all()
    plan_form.plan.choices = [(plan.id, f"{plan.session}" if plan.session else f"Plan {plan.id}") for plan in plans]
    
    if 'submit_plan' in request.form and plan_form.validate_on_submit():
        selected_plan_id = plan_form.plan.data
        return redirect(url_for('evaluation.select_evaluation', plan_id=selected_plan_id))
    
    return render_template('evaluation/select_plan.html', form=plan_form, course_id=course_id)


@evaluation_bp.route('/select_evaluation/<int:plan_id>', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def select_evaluation(plan_id):
    plan = PlanDeCours.query.get_or_404(plan_id)
    evaluations = PlanDeCoursEvaluations.query.filter_by(plan_de_cours_id=plan_id).all()
    
    if not evaluations:
        flash('Aucune évaluation disponible pour ce plan.', 'warning')
        return redirect(url_for('evaluation.select_plan', course_id=plan.cours_id))
    
    form = EvaluationSelectionForm()
    form.evaluation.choices = [(eval.id, eval.titre_evaluation) for eval in evaluations]
    
    # Ajout du champ description
    selected_evaluation = None
    if request.method == 'GET' and request.args.get('evaluation_id'):
        selected_evaluation = PlanDeCoursEvaluations.query.get(request.args.get('evaluation_id'))
    
    if form.validate_on_submit():
        selected_evaluation_id = form.evaluation.data
        description = request.form.get('description', '')
        
        # Mise à jour de la description
        evaluation = PlanDeCoursEvaluations.query.get(selected_evaluation_id)
        if evaluation:
            evaluation.description = description
            db.session.commit()
            flash('Description mise à jour avec succès.', 'success')
            
        return redirect(url_for('evaluation.configure_grid', evaluation_id=selected_evaluation_id))
    
    return render_template(
        'evaluation/select_evaluation.html', 
        form=form, 
        plan=plan, 
        selected_evaluation=selected_evaluation
    )

from collections import defaultdict

@evaluation_bp.route('/configure_grid/<int:evaluation_id>', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def configure_grid(evaluation_id):
    evaluation = PlanDeCoursEvaluations.query.get_or_404(evaluation_id)
    plan = evaluation.plan_de_cours
    plan_id = plan.id

    eval_capacites = (
        PlanDeCoursEvaluationsCapacites.query
        .join(PlanCadreCapacites)
        .join(PlanCadre)
        .filter(PlanCadre.cours_id == plan.cours_id)
        .filter(PlanDeCoursEvaluationsCapacites.evaluation_id == evaluation_id)
        .filter(PlanDeCoursEvaluationsCapacites.capacite_id.isnot(None))
        .filter(db.cast(db.func.replace(PlanDeCoursEvaluationsCapacites.ponderation, '%', ''), db.Float) > 0)
        .options(
            db.joinedload(PlanDeCoursEvaluationsCapacites.capacite)
            .joinedload(PlanCadreCapacites.savoirs_faire)
        )
        .all()
    )

    form = EvaluationGridForm()

    grouped_cf = defaultdict(dict)
    for eval_cap in eval_capacites:
        if eval_cap.capacite and eval_cap.capacite.capacite:
            capacite_nom = eval_cap.capacite.capacite
            capacite_id = eval_cap.capacite.id
            for sf in eval_cap.capacite.savoirs_faire:
                if sf.id not in grouped_cf[capacite_nom]:
                    grouped_cf[capacite_nom][sf.id] = {
                        'texte': sf.texte,
                        'capacite_id': capacite_id,
                        'savoir_faire_id': sf.id,
                        'cible': sf.cible,
                        'seuil_reussite': sf.seuil_reussite
                    }

    if request.method == 'GET':
        form.evaluations.entries = []
        existing_assocs = EvaluationSavoirFaire.query.filter_by(evaluation_id=evaluation_id).all()
        existing_sf = {(assoc.savoir_faire_id, assoc.capacite_id) for assoc in existing_assocs}

        eval_form_data = {
            'evaluation_id': evaluation.id,
            'evaluation_titre': evaluation.titre_evaluation,
            'savoir_faire': []
        }

        processed_sf = set()
        for capacite_nom, savoirs_faire in grouped_cf.items():
            for sf_id, sf_data in savoirs_faire.items():
                if sf_id not in processed_sf:
                    is_selected = (sf_id, sf_data['capacite_id']) in existing_sf
                    savoir_faire_data = {
                        'capacite_id': str(sf_data['capacite_id']),
                        'capacite_nom': capacite_nom,
                        'savoir_faire_id': str(sf_id),
                        'savoir_faire_nom': sf_data['texte'],
                        'savoir_faire_cible': str(sf_data['cible'] or ''),
                        'savoir_faire_seuil': str(sf_data['seuil_reussite'] or ''),
                        'selected': is_selected
                    }
                    eval_form_data['savoir_faire'].append(savoir_faire_data)
                    processed_sf.add(sf_id)

        form.evaluations.append_entry(eval_form_data)

    if form.validate_on_submit():
        try:
            eval_form = form.evaluations[0]
            eval_id = eval_form.evaluation_id.data

            EvaluationSavoirFaire.query.filter_by(evaluation_id=eval_id).delete()

            sf_processed = set()

            selected_savoirs_faire = []

            for sf_form in eval_form.savoir_faire:
                if sf_form.selected.data:
                    savoir_faire_id = int(sf_form.savoir_faire_id.data)
                    capacite_id = int(sf_form.capacite_id.data)
                    sf_key = (savoir_faire_id, capacite_id)
                    if sf_key in sf_processed:
                        continue

                    new_sf_assoc = EvaluationSavoirFaire(
                        evaluation_id=eval_id,
                        savoir_faire_id=savoir_faire_id,
                        capacite_id=capacite_id,
                        selected=True
                    )
                    db.session.add(new_sf_assoc)
                    sf_processed.add(sf_key)
                    selected_savoirs_faire.append(new_sf_assoc)

            db.session.commit()
            flash('Grille d\'évaluation enregistrée avec succès.', 'success')
            if not selected_savoirs_faire:
                flash('Veuillez sélectionner au moins un savoir-faire avant de configurer la grille.', 'warning')
                return redirect(url_for('evaluation.select_evaluation', plan_id=plan_id))
            return redirect(url_for('evaluation.configure_six_level_grid', evaluation_id=evaluation_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'enregistrement: {str(e)}', 'danger')

    return render_template('evaluation/configure_grid.html', form=form, plan=plan, 
                         evaluation=evaluation, grouped_cf=grouped_cf)


@evaluation_bp.route('/configure_six_level_grid/<int:evaluation_id>', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def configure_six_level_grid(evaluation_id):
    evaluation = PlanDeCoursEvaluations.query.get_or_404(evaluation_id)
    form = SixLevelGridForm()
    
    if request.method == 'GET':
        # Get selected savoir-faire with eager loading
        selected_savoirs_faire = EvaluationSavoirFaire.query\
            .options(
                db.joinedload(EvaluationSavoirFaire.savoir_faire),
                db.joinedload(EvaluationSavoirFaire.capacite)
            )\
            .filter_by(
                evaluation_id=evaluation_id,
                selected=True
            ).all()
        
        if not selected_savoirs_faire:
            flash('Aucun savoir-faire sélectionné pour cette évaluation.', 'warning')
            return redirect(url_for('evaluation.select_evaluation', plan_id=evaluation.plan_de_cours.id))
        
        # Clear existing entries
        while len(form.evaluations):
            form.evaluations.pop_entry()
            
        # Add entries for each selected savoir-faire
        for assoc in selected_savoirs_faire:
            form.evaluations.append_entry({
                'evaluation_id': assoc.evaluation_id,
                'savoir_faire_id': assoc.savoir_faire_id,
                'capacite_id': assoc.capacite_id,
                'savoir_faire_nom': assoc.savoir_faire.texte,
                'capacite_nom': assoc.capacite.capacite if assoc.capacite else "Capacité inconnue",
                'selected': assoc.selected,
                'level1_description': assoc.level1_description or '',
                'level2_description': assoc.level2_description or '',
                'level3_description': assoc.level3_description or '',
                'level4_description': assoc.level4_description or '',
                'level5_description': assoc.level5_description or '',
                'level6_description': assoc.level6_description or ''
            })

    
    if form.validate_on_submit():
        try:
            # Clear existing associations
            EvaluationSavoirFaire.query.filter_by(evaluation_id=evaluation_id).delete()
            
            for entry in form.evaluations:
                if entry.selected.data:
                    new_assoc = EvaluationSavoirFaire(
                        evaluation_id=int(entry.evaluation_id.data),
                        savoir_faire_id=int(entry.savoir_faire_id.data),
                        capacite_id=int(entry.capacite_id.data),
                        selected=True,
                        level1_description=entry.level1_description.data,
                        level2_description=entry.level2_description.data,
                        level3_description=entry.level3_description.data,
                        level4_description=entry.level4_description.data,
                        level5_description=entry.level5_description.data,
                        level6_description=entry.level6_description.data
                    )
                    db.session.add(new_assoc)
            
            db.session.commit()
            flash('Grille à six niveaux enregistrée avec succès.', 'success')
            return redirect(url_for('evaluation.configure_six_level_grid', evaluation_id=evaluation_id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'enregistrement: {str(e)}', 'danger')
    
    return render_template(
        'evaluation/configure_six_level_grid.html',
        form=form,
        evaluation=evaluation
    )

@evaluation_bp.route('/generate_six_level_grid', methods=['POST'])
@login_required
@ensure_profile_completed
def generate_six_level_grid():
    """
    Génère automatiquement la grille à six niveaux en appelant OpenAI avec un format structuré.
    """
    data = request.get_json()
    savoir_faire = data.get('savoir_faire', '')
    capacite = data.get('capacite', '')
    savoir_faire_id = data.get('savoir_faire_id')
    evaluation_id = data.get('evaluation_id')  # Ajout de l'evaluation_id
    settings = GrillePromptSettings.get_current()

    # Récupérer l'évaluation et sa description
    evaluation_description = ""
    if evaluation_id:
        try:
            evaluation = PlanDeCoursEvaluations.query.get(evaluation_id)
            if evaluation:
                evaluation_description = evaluation.description or ""
        except Exception as e:
            print(f"Erreur lors de la récupération de l'évaluation: {str(e)}")

    if not savoir_faire or not capacite:
        return jsonify({'error': 'Savoir-faire et capacité requis'}), 400

    # Vérifier que l'ID est valide
    if savoir_faire_id:
        try:
            savoir_faire_id = int(savoir_faire_id)
            sf_info = PlanCadreCapaciteSavoirsFaire.query.get(savoir_faire_id)
            cible = sf_info.cible if sf_info and sf_info.cible else "Réalisation complète et autonome de la tâche"
            seuil = sf_info.seuil_reussite if sf_info and sf_info.seuil_reussite else "Réalisation minimale acceptable de la tâche"
        except (ValueError, TypeError):
            cible = "Réalisation complète et autonome de la tâche"
            seuil = "Réalisation minimale acceptable de la tâche"
    else:
        cible = "Réalisation complète et autonome de la tâche"
        seuil = "Réalisation minimale acceptable de la tâche"

    schema_json = json.dumps(AISixLevelGridResponse.get_schema_with_descriptions(), indent=4, ensure_ascii=False)
    
    prompt = settings.prompt_template.format(
        savoir_faire=savoir_faire,
        capacite=capacite, 
        seuil=seuil,
        cible=cible,
        description_eval=evaluation_description,
        schema=schema_json  # Ajout du schéma
    )

    # Vérification des crédits de l'utilisateur
    user = db.session.get(User, current_user.id)
    if user.credits is None:
        user.credits = 0.0
    if user.credits <= 0:
        return jsonify({'error': 'Crédits insuffisants. Veuillez recharger votre compte.'}), 403

    if not user or not user.openai_key:
        return jsonify({'error': 'Clé OpenAI non configurée'}), 400

    ai_model = "gpt-4o"

    user_credits = user.credits
    user_id = current_user.id

    try:
        client = OpenAI(api_key=current_user.openai_key)

        response = client.beta.chat.completions.parse(
            model=ai_model,
            messages=[{"role": "user", "content": prompt}],
            response_format=AISixLevelGridResponse,
        )
        total_prompt_tokens = 0
        total_completion_tokens = 0

        # Récupérer la consommation (tokens) du premier appel
        if hasattr(response, 'usage'):
            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens

        usage_prompt = response.usage.prompt_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.completion_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)

        new_credits = user_credits - cost

        db.session.execute(
            text("UPDATE User SET credits = :credits WHERE id = :uid"),
            {"credits": new_credits, "uid": user_id}
        )
        db.session.commit()

        structured_data = response.choices[0].message.parsed

        return jsonify(structured_data.model_dump())  # Convertir en dict JSON

    except OpenAIError as e:
        return jsonify({'error': f'Erreur API OpenAI: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Erreur interne: {str(e)}'}), 500

@evaluation_bp.route('/evaluation-wizard', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
def evaluation_wizard():
    # Initialisation des formulaires
    course_form = CourseSelectionForm()
    plan_form = PlanSelectionForm()
    evaluation_form = EvaluationSelectionForm()
    
    # Variables pour stocker les données
    selected_course_id = None
    selected_plan_id = None
    selected_evaluation = None
    grouped_cf = {}
    
    # Remplir les choix du formulaire de cours avec une option vide au début
    user_program_ids = [programme.id for programme in current_user.programmes]
    courses = Cours.query.filter(Cours.programme_id.in_(user_program_ids)).all()
    course_form.course.choices = [('', '-- Sélectionner un cours --')] + [
        (str(course.id), f"{course.code} - {course.nom}") 
        for course in courses
    ]
    
    # Définir le coerce pour permettre les valeurs vides
    course_form.course.coerce = lambda x: int(x) if x else None

    if request.method == 'POST':
        selected_course_id = request.form.get('course')
        selected_plan_id = request.form.get('plan')
        
        # Remplir les choix du plan si un cours est sélectionné
        if selected_course_id:
            plans = PlanDeCours.query.filter_by(cours_id=int(selected_course_id)).order_by(PlanDeCours.session.desc()).all()
            plan_form.plan.choices = [
                (str(plan.id), f"{plan.session}" if plan.session else f"Plan {plan.id}")
                for plan in plans
            ]
        
        # Remplir les choix d'évaluation si un plan est sélectionné
        if selected_plan_id:
            evaluations = PlanDeCoursEvaluations.query.filter_by(
                plan_de_cours_id=int(selected_plan_id)
            ).all()
            evaluation_form.evaluation.choices = [
                (str(eval.id), eval.titre_evaluation) for eval in evaluations
            ]
                
        # Gestion de la sélection de l'évaluation
        if 'submit_evaluation' in request.form:
            evaluation_id = request.form.get('evaluation')
            if evaluation_id:
                selected_evaluation = PlanDeCoursEvaluations.query.get_or_404(int(evaluation_id))
                
                # Récupérer les capacités et savoirs-faire
                eval_capacites = (
                    PlanDeCoursEvaluationsCapacites.query
                    .join(PlanCadreCapacites)
                    .join(PlanCadre)
                    .filter(PlanCadre.cours_id == int(selected_course_id))
                    .filter(PlanDeCoursEvaluationsCapacites.capacite_id.isnot(None))
                    .options(
                        db.joinedload(PlanDeCoursEvaluationsCapacites.capacite)
                        .joinedload(PlanCadreCapacites.savoirs_faire)
                    )
                    .all()
                )
                
                # Récupérer les savoirs-faire déjà sélectionnés
                existing_sf = EvaluationSavoirFaire.query.filter_by(
                    evaluation_id=int(evaluation_id)
                ).all()
                selected_sf_ids = {sf.savoir_faire_id for sf in existing_sf}
                
                # Grouper les capacités et leurs savoirs-faire
                grouped_cf = defaultdict(dict)
                for eval_cap in eval_capacites:
                    if eval_cap.capacite and eval_cap.capacite.capacite:
                        capacite_nom = eval_cap.capacite.capacite
                        capacite_id = eval_cap.capacite.id
                        for sf in eval_cap.capacite.savoirs_faire:
                            if sf.id not in grouped_cf[capacite_nom]:
                                existing_sf_data = next(
                                    (ex_sf for ex_sf in existing_sf if ex_sf.savoir_faire_id == sf.id),
                                    None
                                )
                                grouped_cf[capacite_nom][sf.id] = {
                                    'texte': sf.texte,
                                    'capacite_id': capacite_id,
                                    'savoir_faire_id': sf.id,
                                    'selected': sf.id in selected_sf_ids,
                                    'level1': existing_sf_data.level1_description if existing_sf_data else '',
                                    'level2': existing_sf_data.level2_description if existing_sf_data else '',
                                    'level3': existing_sf_data.level3_description if existing_sf_data else '',
                                    'level4': existing_sf_data.level4_description if existing_sf_data else '',
                                    'level5': existing_sf_data.level5_description if existing_sf_data else '',
                                    'level6': existing_sf_data.level6_description if existing_sf_data else ''
                                }

        # Gestion de la mise à jour de la grille
        if 'update_grid' in request.form:
            evaluation_id = request.form.get('evaluation_id')
            
            try:
                if evaluation_id:
                    # Suppression des anciennes associations
                    EvaluationSavoirFaire.query.filter_by(
                        evaluation_id=int(evaluation_id)
                    ).delete()
                    
                    # Création des nouvelles associations avec descriptions
                    for sf_id in request.form.getlist('savoirs_faire'):
                        capacite_id = request.form.get(f'capacite_{sf_id}')
                        if capacite_id:
                            new_assoc = EvaluationSavoirFaire(
                                evaluation_id=int(evaluation_id),
                                savoir_faire_id=int(sf_id),
                                capacite_id=int(capacite_id),
                                selected=True,
                                level1_description=request.form.get(f'level1_{sf_id}', ''),
                                level2_description=request.form.get(f'level2_{sf_id}', ''),
                                level3_description=request.form.get(f'level3_{sf_id}', ''),
                                level4_description=request.form.get(f'level4_{sf_id}', ''),
                                level5_description=request.form.get(f'level5_{sf_id}', ''),
                                level6_description=request.form.get(f'level6_{sf_id}', '')
                            )
                            db.session.add(new_assoc)
                    
                    db.session.commit()
                    flash('Grille mise à jour avec succès', 'success')
                    
            except Exception as e:
                db.session.rollback()
                flash(f'Erreur: {str(e)}', 'danger')

    return render_template(
        'evaluation/wizard.html',
        course_form=course_form,
        plan_form=plan_form,
        evaluation_form=evaluation_form,
        selected_course_id=selected_course_id,
        selected_plan_id=selected_plan_id,
        selected_evaluation=selected_evaluation,
        grouped_cf=grouped_cf
    )

@evaluation_bp.route('/get_plans', methods=['POST'])
@login_required
@ensure_profile_completed
def get_plans():
    course_id = request.form.get('course_id')
    if not course_id:
        return jsonify({'plans': []})
    
    plans = PlanDeCours.query.filter_by(cours_id=int(course_id)).order_by(PlanDeCours.session.desc()).all()
    return jsonify({
        'plans': [{
            'id': plan.id,  # Pas besoin de convertir en str ici
            'name': f"{plan.session}" if plan.session else f"Plan {plan.id}"
        } for plan in plans]
    })

@evaluation_bp.route('/get_evaluations', methods=['POST'])
@login_required
@ensure_profile_completed
def get_evaluations():
    plan_id = request.form.get('plan_id')
    if not plan_id:
        return jsonify({'evaluations': []})
    
    evaluations = PlanDeCoursEvaluations.query.filter_by(plan_de_cours_id=int(plan_id)).all()
    return jsonify({
        'evaluations': [{'id': str(eval.id), 'title': eval.titre_evaluation} 
                       for eval in evaluations]
    })

@evaluation_bp.route('/get_grid', methods=['POST'])
@login_required
@ensure_profile_completed
def get_grid():
    evaluation_id = request.form.get('evaluation_id')
    if not evaluation_id:
        return ""
        
    evaluation = PlanDeCoursEvaluations.query.get_or_404(int(evaluation_id))
    
    # Récupérer les capacités et savoirs-faire
    eval_capacites = (
        PlanDeCoursEvaluationsCapacites.query
        .join(PlanCadreCapacites)
        .join(PlanCadre)
        .filter(PlanCadre.cours_id == evaluation.plan_de_cours.cours_id)
        .filter(PlanDeCoursEvaluationsCapacites.capacite_id.isnot(None))
        .options(
            db.joinedload(PlanDeCoursEvaluationsCapacites.capacite)
            .joinedload(PlanCadreCapacites.savoirs_faire)
        )
        .all()
    )
    
    # Récupérer les savoirs-faire déjà sélectionnés
    existing_sf = EvaluationSavoirFaire.query.filter_by(
        evaluation_id=int(evaluation_id)
    ).all()
    selected_sf_ids = {sf.savoir_faire_id for sf in existing_sf}
    
    # Grouper les capacités et leurs savoirs-faire
    grouped_cf = defaultdict(dict)
    for eval_cap in eval_capacites:
        if eval_cap.capacite and eval_cap.capacite.capacite:
            capacite_nom = eval_cap.capacite.capacite
            capacite_id = eval_cap.capacite.id
            for sf in eval_cap.capacite.savoirs_faire:
                if sf.id not in grouped_cf[capacite_nom]:
                    existing_sf_data = next(
                        (ex_sf for ex_sf in existing_sf if ex_sf.savoir_faire_id == sf.id),
                        None
                    )
                    grouped_cf[capacite_nom][sf.id] = {
                        'texte': sf.texte,
                        'capacite_id': capacite_id,
                        'savoir_faire_id': sf.id,
                        'selected': sf.id in selected_sf_ids,
                        'level1': existing_sf_data.level1_description if existing_sf_data else '',
                        'level2': existing_sf_data.level2_description if existing_sf_data else '',
                        'level3': existing_sf_data.level3_description if existing_sf_data else '',
                        'level4': existing_sf_data.level4_description if existing_sf_data else '',
                        'level5': existing_sf_data.level5_description if existing_sf_data else '',
                        'level6': existing_sf_data.level6_description if existing_sf_data else ''
                    }
    
    return render_template(
        'evaluation/_grid_content.html',
        selected_evaluation=evaluation,
        grouped_cf=grouped_cf
    )

@evaluation_bp.route('/save_grid', methods=['POST'])
@login_required
@ensure_profile_completed
def save_grid():
    try:
        # Récupérer evaluation_id et description depuis les deux possibilités
        evaluation_id = request.form.get('evaluation_id') or request.form.get('evaluation')
        description = request.form.get('description') or request.form.get('evaluation_description')
        
        if not evaluation_id:
            raise ValueError("ID d'évaluation manquant.")
        
        try:
            evaluation_id = int(evaluation_id)
        except ValueError:
            raise ValueError("ID d'évaluation invalide.")
        
        evaluation = PlanDeCoursEvaluations.query.get(evaluation_id)
        if not evaluation:
            raise ValueError("Évaluation non trouvée.")
        
        # Mettre à jour la description
        evaluation.description = description
        db.session.commit()

        # Vérifier si 'savoirs_faire' est présent dans la requête
        savoirs_faire = request.form.getlist('savoirs_faire')
        if savoirs_faire:
            # Suppression des anciennes associations
            EvaluationSavoirFaire.query.filter_by(
                evaluation_id=evaluation_id
            ).delete()
            
            # Création des nouvelles associations avec descriptions
            for sf_id in savoirs_faire:
                capacite_id = request.form.get(f'capacite_{sf_id}')
                if capacite_id:
                    try:
                        sf_id = int(sf_id)
                        capacite_id = int(capacite_id)
                    except ValueError:
                        raise ValueError("ID de savoir-faire ou de capacité invalide.")
                    
                    new_assoc = EvaluationSavoirFaire(
                        evaluation_id=evaluation_id,
                        savoir_faire_id=sf_id,
                        capacite_id=capacite_id,
                        selected=True,
                        level1_description=request.form.get(f'level1_{sf_id}', ''),
                        level2_description=request.form.get(f'level2_{sf_id}', ''),
                        level3_description=request.form.get(f'level3_{sf_id}', ''),
                        level4_description=request.form.get(f'level4_{sf_id}', ''),
                        level5_description=request.form.get(f'level5_{sf_id}', ''),
                        level6_description=request.form.get(f'level6_{sf_id}', '')
                    )
                    db.session.add(new_assoc)
            
            db.session.commit()
        else:
            # Si 'savoirs_faire' n'est pas présent, ne faire que la mise à jour de la description
            pass
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur lors de la sauvegarde de la grille: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500

@evaluation_bp.route('/export_docx/<int:evaluation_id>', methods=['GET'])
@login_required
@ensure_profile_completed
def export_evaluation_docx(evaluation_id):
    # 1. Récupérer l'évaluation
    evaluation = PlanDeCoursEvaluations.query.get_or_404(evaluation_id)
    
    # 2. Récupérer les capacités et savoirs-faire associés
    eval_capacites = (
        PlanDeCoursEvaluationsCapacites.query
        .join(PlanCadreCapacites)
        .join(PlanCadre)
        .filter(PlanCadre.cours_id == evaluation.plan_de_cours.cours_id)
        .filter(PlanDeCoursEvaluationsCapacites.capacite_id.isnot(None))
        .options(
            db.joinedload(PlanDeCoursEvaluationsCapacites.capacite)
            .joinedload(PlanCadreCapacites.savoirs_faire)
        )
        .all()
    )
    
    # 3. Récupérer les savoirs-faire avec leurs descriptions de niveaux
    eval_savoirs_faire = EvaluationSavoirFaire.query.filter_by(
        evaluation_id=evaluation_id
    ).all()
    
    # 4. Organiser les données pour le template
    grouped_cf = defaultdict(dict)
    for eval_cap in eval_capacites:
        if eval_cap.capacite and eval_cap.capacite.capacite:
            capacite_nom = eval_cap.capacite.capacite
            for sf in eval_cap.capacite.savoirs_faire:
                existing_sf_data = next(
                    (esf for esf in eval_savoirs_faire if esf.savoir_faire_id == sf.id),
                    None
                )
                if existing_sf_data:
                    grouped_cf[capacite_nom][sf.id] = {
                        'texte': sf.texte,
                        'level1': existing_sf_data.level1_description,
                        'level2': existing_sf_data.level2_description,
                        'level3': existing_sf_data.level3_description,
                        'level4': existing_sf_data.level4_description,
                        'level5': existing_sf_data.level5_description,
                        'level6': existing_sf_data.level6_description
                    }
    
    # 5. Charger le template Word
    base_path = Path(__file__).parent.parent.parent
    template_path = os.path.join(base_path, 'static', 'docs', 'evaluation_grid_template.docx')
    
    if not os.path.exists(template_path):
        current_app.logger.error(f"Template not found at: {template_path}")
        flash("Erreur: Le template de la grille d'évaluation est introuvable.", "error")
        return redirect(url_for('evaluation.view_evaluation', evaluation_id=evaluation_id))

    doc = DocxTemplate(template_path)
    
    # 6. Préparer le contexte pour le template
    context = {
        'evaluation': evaluation,
        'capacites_savoirs_faire': grouped_cf,
        'cours': evaluation.plan_de_cours.cours,
        'plan_de_cours': evaluation.plan_de_cours
    }
    
    # 7. Rendre le document
    doc.render(context)
    
    # 8. Préparer le document pour le téléchargement
    byte_io = io.BytesIO()
    doc.save(byte_io)
    byte_io.seek(0)
    
    # 9. Envoyer le fichier
    filename = f"Grille_evaluation_{evaluation.plan_de_cours.session}.docx"
    return send_file(
        byte_io,
        download_name=filename,
        as_attachment=True
    )