import os
import uuid
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, jsonify
from flask_login import login_required, current_user
from ..forms import FileUploadForm
from ..tasks.import_grille import extract_grille_from_pdf_task
import logging
from celery.result import AsyncResult
from ...celery_app import celery
from ..forms import (
    ConfirmationGrilleForm
)

from ..models import db, BackupConfig, User, Competence, ElementCompetence, ElementCompetenceCriteria, \
                   ElementCompetenceParCours, FilConducteur, CoursPrealable, CoursCorequis, CompetenceParCours, \
                   PlanCadre, PlanCadreCoursCorequis, PlanCadreCapacites, PlanCadreCapaciteSavoirsNecessaires, \
                   PlanCadreCapaciteSavoirsFaire, PlanCadreCapaciteMoyensEvaluation, PlanCadreSavoirEtre, \
                   PlanCadreObjetsCibles, PlanCadreCoursRelies, PlanCadreCoursPrealables, \
                   PlanCadreCompetencesCertifiees, PlanCadreCompetencesDeveloppees, PlanDeCours, PlanDeCoursCalendrier, \
                   PlanDeCoursMediagraphie, PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations, \
                   PlanDeCoursEvaluationsCapacites, Department, DepartmentRegles, DepartmentPIEA, \
                   ListeProgrammeMinisteriel, Programme, Cours, ListeCegep, GlobalGenerationSettings, user_programme, CoursCorequis, CoursPrealable

from ...utils import save_grille_to_database

import json


logger = logging.getLogger(__name__)

# Créer le blueprint
grille_bp = Blueprint('grille_bp', __name__, template_folder='templates')

@grille_bp.route('/import_grille', methods=['GET', 'POST'])
@login_required
def import_grille():
    """
    Affiche un formulaire permettant d'importer un fichier PDF, lance la tâche Celery
    et redirige vers une page de suivi du statut de la tâche.
    """
    form = FileUploadForm()
    if form.validate_on_submit():
        # Récupérer le fichier uploadé
        file = form.file.data
        
        # Créer un nom de fichier unique
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        # Définir le dossier d'upload depuis la config ou 'uploads' par défaut
        upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"))
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        # Récupérer la clé API du current_user
        openai_key = current_user.openai_key
        
        # Lancer la tâche Celery de traitement du PDF
        task = extract_grille_from_pdf_task.delay(pdf_path=filepath, openai_key=openai_key)
        
        flash("Le fichier a été importé et la tâche a été lancée. Veuillez patienter...", "info")
        # Rediriger vers la page de suivi unifiée
        return redirect(url_for('tasks.track_task', task_id=task.id))
    return render_template('import_grille.html', form=form)


@grille_bp.route('/grille/import', methods=['POST'])
@login_required
def import_grille_start():
    """Unified start endpoint for grille import (PDF -> Celery task).

    Accepts multipart FormData with key 'file'. Returns { task_id } and 202.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Aucun fichier fourni.'}), 400
        file = request.files['file']
        if not file or not file.filename:
            return jsonify({'error': 'Fichier invalide.'}), 400
        # Build upload path
        upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"))
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        # Enqueue Celery task
        openai_key = current_user.openai_key
        task = extract_grille_from_pdf_task.delay(pdf_path=filepath, openai_key=openai_key)
        return jsonify({'task_id': task.id}), 202
    except Exception as e:
        logger.exception('Erreur lors du démarrage de l\'import de grille')
        return jsonify({'error': str(e)}), 500


@grille_bp.route('/liste_grilles')
@login_required
def liste_grilles():
    """Affiche la liste des cours importés par programme."""
    # Récupérer les programmes associés à l'utilisateur ou tous les programmes selon le rôle
    if current_user.role in ['admin', 'gestionnaire']:
        programmes = Programme.query.all()
    elif current_user.department_id:
        programmes = Programme.query.filter_by(department_id=current_user.department_id).all()
    else:
        programmes = current_user.programmes
    
    # Pour chaque programme, récupérer ses cours organisés par session
    programmes_with_courses = []
    
    for programme in programmes:
        # Récupérer tous les cours du programme
        cours_query = Cours.query.filter_by(programme_id=programme.id).order_by(Cours.session, Cours.code)
        cours_list = cours_query.all()
        
        # Organiser les cours par session
        courses_by_session = {}
        for cours in cours_list:
            session_num = cours.session
            if session_num not in courses_by_session:
                courses_by_session[session_num] = []
            courses_by_session[session_num].append(cours)
        
        # Trier les sessions
        sorted_sessions = sorted(courses_by_session.items())
        
        # Ajouter à la liste
        programmes_with_courses.append({
            'programme': programme,
            'sessions': sorted_sessions
        })
    
    # Passer les classes de modèles au template
    return render_template(
        'liste_grilles.html',
        programmes_with_courses=programmes_with_courses,
        CoursPrealable=CoursPrealable,  # Ajouter cette ligne
        CoursCorequis=CoursCorequis     # Ajouter aussi cette ligne si vous utilisez CoursCorequis dans le template
    )

@grille_bp.route('/confirm_grille_import/<task_id>', methods=['GET', 'POST'])
@login_required
def confirm_grille_import(task_id):
    """
    Affiche un formulaire permettant de confirmer l'importation d'une grille de cours extraite.
    L'utilisateur peut choisir le programme auquel associer la grille.
    """
    # Récupérer le résultat de la tâche
    task_result = AsyncResult(task_id, app=celery)
    
    if task_result.state != 'SUCCESS' or not task_result.result or task_result.result.get('status') != 'success':
        flash("L'extraction n'est pas encore terminée ou a échoué.", "warning")
        return redirect(url_for('tasks.track_task', task_id=task_id))
    
    # Récupérer le JSON de la grille
    try:
        grille_json = task_result.result['result']
        # Accepter dict/list directement, ou parser texte avec reformatage tolérant
        if isinstance(grille_json, (dict, list)):
            grille_data = grille_json
        else:
            def _parse_or_coerce(s):
                s = (s or '').strip()
                # Retirer éventuelles fences Markdown
                for fence in ("```json", "```JSON", "```"):
                    if s.startswith(fence):
                        s = s[len(fence):].strip()
                if s.endswith("```"):
                    s = s[:-3].strip()
                try:
                    return json.loads(s)
                except Exception:
                    pass
                start = s.find('{')
                end = s.rfind('}')
                if start != -1 and end != -1 and end > start:
                    candidate = s[start:end+1]
                    return json.loads(candidate)
                return json.loads(s)  # Laisse lever
            grille_data = _parse_or_coerce(grille_json)

        # Obtenir le nom du programme depuis le JSON
        nom_programme = grille_data.get('programme', 'Programme inconnu')
    except Exception as e:
        logger.error(f"Erreur lors de la lecture du JSON de la grille: {e}", exc_info=True)
        flash(f"Format de données invalide: {str(e)}", "danger")
        return redirect(url_for('grille_bp.import_grille'))
    
    # Créer le formulaire
    form = ConfirmationGrilleForm()
    
    # Remplir la liste déroulante des programmes disponibles
    programmes = Programme.query.join(Department).filter(
        Department.id == current_user.department_id
    ).all() if current_user.department_id else Programme.query.all()
    
    form.programme_id.choices = [(p.id, f"{p.nom}") for p in programmes]
    
    # Pré-remplir avec le nom du programme détecté
    form.nom_programme.data = nom_programme
    
    # Stocker l'ID de la tâche et le JSON pour soumission
    form.task_id.data = task_id
    form.grille_json.data = grille_json
    
    if form.validate_on_submit():
        if form.annuler.data:
            flash("Importation annulée.", "info")
            return redirect(url_for('grille_bp.import_grille'))
        
        if form.confirmer.data:
            try:
                # Récupérer les données du formulaire
                programme_id = form.programme_id.data
                programme = Programme.query.get_or_404(programme_id)
                
                # Sauvegarder en base de données
                success = save_grille_to_database(
                    grille_data=grille_data,
                    programme_id=programme_id,
                    programme_nom=programme.nom,
                    user_id=current_user.id
                )
                
                if success:
                    flash("La grille de cours a été importée avec succès.", "success")
                    # Rediriger vers view_programme au lieu de liste_grilles
                    return redirect(url_for('programme.view_programme', programme_id=programme_id))
                else:
                    flash("Erreur lors de l'importation de la grille de cours.", "danger")
            except Exception as e:
                logger.error(f"Erreur lors de l'importation de la grille: {e}", exc_info=True)
                flash(f"Erreur lors de l'importation: {str(e)}", "danger")
    
    # Préparer un aperçu des données pour affichage
    apercu_sessions = []
    if 'sessions' in grille_data:
        for session in grille_data['sessions']:
            session_info = {
                'numero': session.get('numero_session', 'Session inconnue'),
                'nb_cours': len(session.get('cours', [])),
                'cours_exemples': [c.get('code_cours', '') + ' - ' + c.get('titre_cours', '') 
                                  for c in session.get('cours', [])[:3]]  # Limiter à 3 exemples
            }
            apercu_sessions.append(session_info)
    
    return render_template(
        'confirm_grille_import.html',
        form=form,
        apercu_sessions=apercu_sessions,
        nom_programme=nom_programme,
        task_id=task_id
    )
