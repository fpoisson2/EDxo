# programme.py
from flask import Blueprint, Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from app.forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    MultiCheckboxField,
    PlanCadreForm,
    SavoirEtreForm,
    CompetenceDeveloppeeForm,
    ObjetCibleForm,
    CoursRelieForm,
    CoursPrealableForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm, 
    GenerationSettingForm
)
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import json
import logging
from collections import defaultdict
from openai import OpenAI
from openai import OpenAIError
from utils.decorator import role_required, roles_required
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
import bleach
from docxtpl import DocxTemplate
from io import BytesIO 
from werkzeug.security import generate_password_hash, check_password_hash

# Utilities
from utils.utils import (
    parse_html_to_list,
    parse_html_to_nested_list,
    get_plan_cadre_data,
    replace_tags_jinja2,
    process_ai_prompt,
    generate_docx_with_template
)

# Import SQLAlchemy models
from app.models import (
    db,
    User,
    Programme,
    Competence,
    FilConducteur,
    Cours,
    CoursPrealable,
    CoursCorequis,
    ElementCompetence,
    ElementCompetenceCriteria,
    ElementCompetenceParCours,
)

# Example of another blueprint import (unused here, just as in your snippet)
from app.routes.plan_de_cours import plan_de_cours_bp


import logging
logger = logging.getLogger(__name__)

programme_bp = Blueprint('programme', __name__, url_prefix='/programme')

@programme_bp.route('/<int:programme_id>')
@login_required
def view_programme(programme_id):
    # Debug logging
    logger.debug(f"Accessing programme {programme_id}")
    logger.debug(f"User programmes: {[p.id for p in current_user.programmes]}")
    
    # Récupérer le programme
    programme = Programme.query.get(programme_id)
    if not programme:
        flash('Programme non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Vérifier si l'utilisateur a accès à ce programme
    if programme not in current_user.programmes and current_user.role != 'admin':
        flash("Vous n'avez pas accès à ce programme.", 'danger')
        return render_template('no_access.html')


    # Récupérer les compétences associées
    competences = Competence.query.filter_by(programme_id=programme_id).all()

    # Récupérer les fils conducteurs associés
    fil_conducteurs = FilConducteur.query.filter_by(programme_id=programme_id).all()

    # Récupérer les cours associés au programme + infos fil conducteur
    # (Dans ce modèle, FilConducteur n'est pas forcément relié par relationship, 
    # on utilise donc l’id fil_conducteur_id directement)
    cours = (Cours.query
             .filter_by(programme_id=programme_id)
             .order_by(Cours.session.asc())
             .all())

    # Regrouper les cours par session
    cours_par_session = defaultdict(list)
    for c in cours:
        cours_par_session[c.session].append(c)

    # Récupérer préalables et co-requis pour chaque cours
    prerequisites = {}
    corequisites = {}
    for c in cours:
        # Pré-requis
        preq = (db.session.query(Cours.nom, Cours.code, CoursPrealable.note_necessaire)
                .join(CoursPrealable, Cours.id == CoursPrealable.cours_prealable_id)
                .filter(CoursPrealable.cours_id == c.id)
                .all())
        prerequisites[c.id] = [(f"{p.code} - {p.nom}", p.note_necessaire) for p in preq]

        # Co-requis
        coreq = (db.session.query(Cours.nom, Cours.code)
                 .join(CoursCorequis, Cours.id == CoursCorequis.cours_corequis_id)
                 .filter(CoursCorequis.cours_id == c.id)
                 .all())
        corequisites[c.id] = [f"{cc.code} - {cc.nom}" for cc in coreq]

    # Récupérer les codes des compétences (développées ou atteintes) par cours
    competencies_codes = {}
    for c in cours:
        # Un SELECT DISTINCT sur c.code AS competence_code depuis la table Competence 
        # via ElementCompetence -> ElementCompetenceParCours
        comps = (db.session.query(Competence.code.label('competence_code'))
                 .join(ElementCompetence, Competence.id == ElementCompetence.competence_id)
                 .join(ElementCompetenceParCours, ElementCompetence.id == ElementCompetenceParCours.element_competence_id)
                 .filter(ElementCompetenceParCours.cours_id == c.id)
                 .filter(ElementCompetenceParCours.status.in_(['Développé significativement', 'Atteint']))
                 .distinct()
                 .all())
        competencies_codes[c.id] = [comp.competence_code for comp in comps]

    # Calcul des totaux
    total_heures_theorie = sum(c.heures_theorie for c in cours)
    total_heures_laboratoire = sum(c.heures_laboratoire for c in cours)
    total_heures_travail_maison = sum(c.heures_travail_maison for c in cours)
    total_unites = sum(c.nombre_unites for c in cours)

    # Créer des dictionnaires de formulaires de suppression
    delete_forms_competences = {comp.id: DeleteForm(prefix=f"competence-{comp.id}") for comp in competences}
    delete_forms_cours = {c.id: DeleteForm(prefix=f"cours-{c.id}") for c in cours}

    # Récupérer tous les programmes (pour le sélecteur éventuel)
    programmes = current_user.programmes

    return render_template('view_programme.html',
                           programme=programme,
                           programmes=programmes,
                           competences=competences,
                           fil_conducteurs=fil_conducteurs,
                           cours_par_session=cours_par_session,
                           delete_forms_competences=delete_forms_competences,
                           delete_forms_cours=delete_forms_cours,
                           prerequisites=prerequisites,
                           corequisites=corequisites,
                           competencies_codes=competencies_codes,
                           total_heures_theorie=total_heures_theorie,
                           total_heures_laboratoire=total_heures_laboratoire,
                           total_heures_travail_maison=total_heures_travail_maison,
                           total_unites=total_unites
                           )


@programme_bp.route('/competence/<int:competence_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def edit_competence(competence_id):
    form = CompetenceForm()
    # Récupérer la compétence
    competence = Competence.query.get(competence_id)
    # Récupérer la liste des programmes
    programmes = Programme.query.all()

    if competence is None:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Peupler le choix de programme
    form.programme.choices = [(p.id, p.nom) for p in programmes]

    if request.method == 'POST' and form.validate_on_submit():
        try:
            competence.programme_id = form.programme.data
            competence.code = form.code.data
            competence.nom = form.nom.data
            competence.criteria_de_performance = form.criteria_de_performance.data
            competence.contexte_de_realisation = form.contexte_de_realisation.data

            db.session.commit()
            flash('Compétence mise à jour avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=competence.programme_id))
        except Exception as e:
            flash(f'Erreur lors de la mise à jour de la compétence : {e}', 'danger')
            return redirect(url_for('programme.edit_competence', competence_id=competence_id))
    else:
        # Pré-remplir le formulaire
        form.programme.data = competence.programme_id
        form.code.data = competence.code if competence.code else ''
        form.nom.data = competence.nom
        form.criteria_de_performance.data = competence.criteria_de_performance
        form.contexte_de_realisation.data = competence.contexte_de_realisation

    return render_template('edit_competence.html', form=form, competence=competence)


@programme_bp.route('/competence/<int:competence_id>/delete', methods=['POST'])
@role_required('admin')
def delete_competence(competence_id):
    # Formulaire de suppression
    delete_form = DeleteForm(prefix=f"competence-{competence_id}")

    if delete_form.validate_on_submit():
        competence = Competence.query.get(competence_id)
        if not competence:
            flash('Compétence non trouvée.', 'danger')
            return redirect(url_for('main.index'))

        programme_id = competence.programme_id
        try:
            db.session.delete(competence)
            db.session.commit()
            flash('Compétence supprimée avec succès!', 'success')
        except Exception as e:
            flash(f'Erreur lors de la suppression de la compétence : {e}', 'danger')

        return redirect(url_for('programme.view_programme', programme_id=programme_id))
    else:
        flash('Formulaire de suppression invalide.', 'danger')
        return redirect(url_for('main.index'))


@programme_bp.route('/competence/code/<string:competence_code>')
@role_required('admin')
def view_competence_by_code(competence_code):
    # Récupérer la compétence par son code
    competence = Competence.query.filter_by(code=competence_code).first()

    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Rediriger vers la route existante avec competence_id
    return redirect(url_for('programme.view_competence', competence_id=competence.id))


@programme_bp.route('/competence/<int:competence_id>')
@login_required
def view_competence(competence_id):
    # Récupération de la compétence + programme lié
    competence = Competence.query.get(competence_id)
    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Nettoyage HTML
    allowed_tags = [
        'ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
    ]
    allowed_attributes = {
        'a': ['href', 'title', 'target']
    }

    criteria_content = competence.criteria_de_performance or ""
    context_content = competence.contexte_de_realisation or ""

    # Assurer que ce sont des chaînes
    if not isinstance(criteria_content, str):
        criteria_content = str(criteria_content)
    if not isinstance(context_content, str):
        context_content = str(context_content)

    try:
        criteria_html = bleach.clean(
            criteria_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
        context_html = bleach.clean(
            context_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
    except Exception as e:
        flash(f'Erreur lors du nettoyage du contenu : {e}', 'danger')
        criteria_html = ""
        context_html = ""

    # Récupérer les éléments de compétence et leurs critères
    # Dans le modèle SQLAlchemy, un Competence possède un relationship 'elements'
    # et chaque ElementCompetence possède un relationship 'criteria'
    elements_comp = competence.elements  # liste de ElementCompetence

    # Organiser les critères par élément de compétence
    elements_dict = {}
    for element in elements_comp:
        elements_dict[element.id] = {
            'nom': element.nom,
            'criteres': [c.criteria for c in element.criteria]
        }

    # Instancier le formulaire de suppression
    delete_form = DeleteForm(prefix=f"competence-{competence.id}")

    return render_template(
        'view_competence.html',
        competence=competence,
        criteria_html=criteria_html,
        context_html=context_html,
        elements_competence=elements_dict,
        delete_form=delete_form
    )
