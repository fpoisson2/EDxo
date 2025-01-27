# routes/evaluation.py

from flask import (
    Blueprint, 
    render_template, 
    redirect, 
    url_for, 
    flash, 
    request
)
from flask_login import login_required
from functools import wraps
from app.models import (
    db, 
    Cours, 
    PlanDeCours, 
    PlanDeCoursEvaluations, 
    PlanCadreCapacites, 
    PlanCadre, 
    Competence,
    PlanDeCoursEvaluationsCapacites,
    EvaluationSavoirFaire
)
from app.forms import (
    CourseSelectionForm, 
    PlanSelectionForm, 
    EvaluationGridForm, 
    EvaluationForm,               # Assurez-vous d'importer EvaluationForm
    SavoirFaireCheckboxForm,
    EvaluationSelectionForm
)
from utils.decorator import roles_required

from collections import defaultdict

evaluation_bp = Blueprint('evaluation', __name__, url_prefix='/evaluation')

def admin_required(f):
    @wraps(f)
    @login_required
    @roles_required('admin')
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function

@evaluation_bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create_evaluation_grid():
    # Étape 1 : Sélection du Cours
    course_form = CourseSelectionForm()
    course_form.course.choices = [(course.id, f"{course.code} - {course.nom}") for course in Cours.query.all()]
    
    if 'submit_course' in request.form and course_form.validate_on_submit():
        selected_course_id = course_form.course.data
        return redirect(url_for('evaluation.select_plan', course_id=selected_course_id))
    
    return render_template('evaluation/select_course.html', form=course_form)

@evaluation_bp.route('/select_plan/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def select_plan(course_id):
    plan_form = PlanSelectionForm()
    plans = PlanDeCours.query.filter_by(cours_id=course_id).all()
    plan_form.plan.choices = [(plan.id, f"Plan {plan.id}") for plan in plans]
    
    if 'submit_plan' in request.form and plan_form.validate_on_submit():
        selected_plan_id = plan_form.plan.data
        return redirect(url_for('evaluation.select_evaluation', plan_id=selected_plan_id))
    
    return render_template('evaluation/select_plan.html', form=plan_form, course_id=course_id)

    
    return render_template('evaluation/select_plan.html', form=plan_form, course_id=course_id)

@evaluation_bp.route('/select_evaluation/<int:plan_id>', methods=['GET', 'POST'])
@admin_required
def select_evaluation(plan_id):
    plan = PlanDeCours.query.get_or_404(plan_id)
    evaluations = PlanDeCoursEvaluations.query.filter_by(plan_de_cours_id=plan_id).all()
    
    if not evaluations:
        flash('Aucune évaluation disponible pour ce plan.', 'warning')
        return redirect(url_for('evaluation.select_plan', course_id=plan.cours_id))
    
    form = EvaluationSelectionForm()
    form.evaluation.choices = [(eval.id, eval.titre_evaluation) for eval in evaluations]
    
    if form.validate_on_submit():
        selected_evaluation_id = form.evaluation.data
        return redirect(url_for('evaluation.configure_grid', evaluation_id=selected_evaluation_id))
    
    return render_template('evaluation/select_evaluation.html', form=form, plan=plan)

# routes/evaluation.py (modification de la route configure_grid)

from collections import defaultdict

@evaluation_bp.route('/configure_grid/<int:evaluation_id>', methods=['GET', 'POST'])
@admin_required
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

    # Prepare grouped data for the template - now tracking savoir_faire origins
    grouped_cf = defaultdict(dict)
    for eval_cap in eval_capacites:
        if eval_cap.capacite and eval_cap.capacite.capacite:
            capacite_nom = eval_cap.capacite.capacite
            capacite_id = eval_cap.capacite.id
            for sf in eval_cap.capacite.savoirs_faire:
                # On utilise un dictionnaire simple au lieu d'un defaultdict imbriqué
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
        
        # Fetch existing associations
        existing_assocs = EvaluationSavoirFaire.query.filter_by(evaluation_id=evaluation_id).all()
        existing_sf = {(assoc.savoir_faire_id, assoc.capacite_id) for assoc in existing_assocs}

        eval_form_data = {
            'evaluation_id': evaluation.id,
            'evaluation_titre': evaluation.titre_evaluation,
            'savoir_faire': []
        }

        # Now we'll only add each savoir-faire once with its correct capacite
        processed_sf = set()  # Track which savoir_faire we've already processed
        for capacite_nom, savoirs_faire in grouped_cf.items():
            for sf_id, sf_data in savoirs_faire.items():
                if sf_id not in processed_sf:  # Only process each savoir-faire once
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

            # Clear existing associations
            EvaluationSavoirFaire.query.filter_by(evaluation_id=eval_id).delete()

            # Track processed savoir-faire to avoid duplicates
            sf_processed = set()

            for sf_form in eval_form.savoir_faire:
                if sf_form.selected.data:
                    savoir_faire_id = int(sf_form.savoir_faire_id.data)
                    capacite_id = int(sf_form.capacite_id.data)
                    
                    # Create unique key for deduplication
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

            db.session.commit()
            flash('Grille d\'évaluation enregistrée avec succès.', 'success')
            return redirect(url_for('evaluation.create_evaluation_grid'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'enregistrement: {str(e)}', 'danger')

    return render_template('evaluation/configure_grid.html', form=form, plan=plan, 
                         evaluation=evaluation, grouped_cf=grouped_cf)