# cours.py
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
    CapaciteItemForm,
    ObjetCibleForm,
    CoursRelieForm,
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
from dotenv import load_dotenv
from utils.decorator import role_required, roles_required, ensure_profile_completed
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
import bleach
from docxtpl import DocxTemplate
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash
from utils.utils import (
    parse_html_to_list,
    parse_html_to_nested_list,
    get_plan_cadre_data,
    replace_tags_jinja2,
    process_ai_prompt,
    generate_docx_with_template
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask_wtf.csrf import validate_csrf, CSRFError
import traceback
from datetime import datetime

from utils.utils import get_programme_id_for_cours, is_coordo_for_programme

# Import all necessary models and the db session
from app.models import (
    db,
    User,
    Cours,
    Programme,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    CoursPrealable,
    CoursCorequis,
    Competence,
    CompetenceParCours,
    ElementCompetence,
    ElementCompetenceParCours
)


cours_bp = Blueprint('cours', __name__, url_prefix='/cours')


# --------------------------------------------------------------------------
# Helper functions (converted to SQLAlchemy)
# --------------------------------------------------------------------------
def get_plan_cadre(plan_id, cours_id):
    """
    Récupère un PlanCadre spécifique relié à un cours via SQLAlchemy.
    """
    return PlanCadre.query.filter_by(id=plan_id, cours_id=cours_id).first()

def get_cours_details(cours_id):
    """
    Récupère l'objet Cours et le renvoie (avec accès à cours.programme).
    """
    return Cours.query.filter_by(id=cours_id).first()

def get_related_courses(cours_id, relation_table, relation_field):
    """
    Récupère les cours liés (préalables ou corequis) et renvoie leurs détails.
    - relation_table: 'CoursPrealable' ou 'CoursCorequis'
    - relation_field: 'cours_prealable_id' ou 'cours_corequis_id'
    """
    if relation_table == 'CoursPrealable':
        entries = CoursPrealable.query.filter_by(cours_id=cours_id).all()
        related_ids = [e.cours_prealable_id for e in entries]
    elif relation_table == 'CoursCorequis':
        entries = CoursCorequis.query.filter_by(cours_id=cours_id).all()
        related_ids = [e.cours_corequis_id for e in entries]
    else:
        related_ids = []

    if not related_ids:
        return []

    return Cours.query.filter(Cours.id.in_(related_ids)).all()

def get_competences(cours_id, type_competence):
    """
    Récupère les compétences (nom uniquement) développées ou atteintes pour un cours.
    """
    if type_competence == 'developpees':
        # Compétences développées
        comps = (
            db.session.query(Competence)
            .join(CompetenceParCours, Competence.id == CompetenceParCours.competence_developpee_id)
            .filter(
                CompetenceParCours.cours_id == cours_id,
                CompetenceParCours.competence_developpee_id.isnot(None)
            )
            .all()
        )
        return comps
    elif type_competence == 'atteintes':
        # Compétences atteintes
        comps = (
            db.session.query(Competence)
            .join(CompetenceParCours, Competence.id == CompetenceParCours.competence_atteinte_id)
            .filter(
                CompetenceParCours.cours_id == cours_id,
                CompetenceParCours.competence_atteinte_id.isnot(None)
            )
            .all()
        )
        return comps
    else:
        return []

def get_elements_competence(cours_id):
    """
    Récupère tous les éléments de compétence rattachés à un cours et les regroupe par compétence.
    """
    # Jointure
    results = (
        db.session.query(ElementCompetenceParCours, ElementCompetence, Competence)
        .join(ElementCompetence, ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
        .join(Competence, ElementCompetence.competence_id == Competence.id)
        .filter(ElementCompetenceParCours.cours_id == cours_id)
        .all()
    )

    grouped = {}
    for ecp, ec, c in results:
        comp_id = c.id
        if comp_id not in grouped:
            grouped[comp_id] = {
                'nom': c.nom,
                'code': c.code,
                'elements': []
            }
        grouped[comp_id]['elements'].append({
            'element_competence_nom': ec.nom,
            'status': ecp.status
        })
    return grouped


# --------------------------------------------------------------------------
# Route pour ajouter un Plan Cadre à un cours
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/plan_cadre/add', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
@ensure_profile_completed
def add_plan_cadre(cours_id):
    try:
        # Créer un plan-cadre avec des valeurs par défaut
        new_plan = PlanCadre(
            cours_id=cours_id,
            place_intro="",
            objectif_terminal="",
            structure_intro="",
            structure_activites_theoriques="",
            structure_activites_pratiques="",
            structure_activites_prevues="",
            eval_evaluation_sommative="",
            eval_nature_evaluations_sommatives="",
            eval_evaluation_de_la_langue="",
            eval_evaluation_sommatives_apprentissages=""
        )
        db.session.add(new_plan)
        db.session.commit()

        flash('Plan Cadre créé avec succès!', 'success')
        # Rediriger vers la page view_plan_cadre
        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=new_plan.id))

    except IntegrityError:
        db.session.rollback()
        flash('Un Plan Cadre existe déjà pour ce cours.', 'danger')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Erreur lors de l\'ajout du Plan Cadre : {e}', 'danger')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))


# --------------------------------------------------------------------------
# Route principale pour visualiser/éditer un Plan Cadre
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>', methods=['GET', 'POST'])
@login_required
@ensure_profile_completed
@ensure_profile_completed
def view_plan_cadre(cours_id, plan_id):
    """
    Affiche ou met à jour un plan-cadre pour un cours donné.
    """
    # Pour debug
    print("DEBUG => request.method:", request.method)
    print("DEBUG => request.form:", request.form.to_dict())

    # Formulaire d'import de plan-cadre (externe)
    import_form = ImportPlanCadreForm()

    plan = get_plan_cadre(plan_id, cours_id)
    cours = get_cours_details(cours_id)

    if not plan or not cours:
        flash('Plan Cadre ou Cours non trouvé.', 'danger')
        return redirect(url_for('cours.view_cours', cours_id=cours_id))

    if request.method == 'GET':
        # Préparer le formulaire principal
        plan_data = {
            'place_intro': plan.place_intro or "",
            'objectif_terminal': plan.objectif_terminal or "",
            'structure_intro': plan.structure_intro or "",
            'structure_activites_theoriques': plan.structure_activites_theoriques or "",
            'structure_activites_pratiques': plan.structure_activites_pratiques or "",
            'structure_activites_prevues': plan.structure_activites_prevues or "",
            'eval_evaluation_sommative': plan.eval_evaluation_sommative or "",
            'eval_nature_evaluations_sommatives': plan.eval_nature_evaluations_sommatives or "",
            'eval_evaluation_de_la_langue': plan.eval_evaluation_de_la_langue or "",
            'eval_evaluation_sommatives_apprentissages': plan.eval_evaluation_sommatives_apprentissages or ""
        }
        plan_form = PlanCadreForm(data=plan_data)

        # Peupler les champs répétés (tables reliées)
        # competences_developpees
        for item in plan.competences_developpees:
            entry = plan_form.competences_developpees.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # objets_cibles
        for item in plan.objets_cibles:
            entry = plan_form.objets_cibles.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # competences_certifiees
        for item in plan.competences_certifiees:
            entry = plan_form.competences_certifiees.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # cours_corequis
        for item in plan.cours_corequis:
            entry = plan_form.cours_corequis.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # cours_prealables
        for item in plan.cours_prealables:
            entry = plan_form.cours_prealables.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # cours_relies
        for item in plan.cours_relies:
            entry = plan_form.cours_relies.append_entry()
            entry.texte.data = item.texte
            entry.texte_description.data = item.description

        # savoir_etre
        for item in plan.savoirs_etre:
            entry = plan_form.savoir_etre.append_entry()
            entry.texte.data = item.texte

        # Formulaire d'AI/génération
        generate_form = GenerateContentForm(
            additional_info=plan.additional_info,
            ai_model=plan.ai_model
        )

        # Capacités
        # Charger depuis la DB et remplir le form
        for cap in plan.capacites:
            form_cap = plan_form.capacites.append_entry()
            form_cap.id = cap.id  # Conserver l'ID pour mises à jour
            form_cap.capacite.data = cap.capacite
            form_cap.description_capacite.data = cap.description_capacite
            form_cap.ponderation_min.data = cap.ponderation_min
            form_cap.ponderation_max.data = cap.ponderation_max

            # Savoirs nécessaires
            for sn in cap.savoirs_necessaires:
                form_cap.savoirs_necessaires.append_entry(sn.texte)

            # Savoirs faire
            for sf in cap.savoirs_faire:
                sf_entry = form_cap.savoirs_faire.append_entry()
                sf_entry.texte.data = sf.texte
                sf_entry.cible.data = sf.cible if sf.cible else ""
                sf_entry.seuil_reussite.data = sf.seuil_reussite if sf.seuil_reussite else ""

            # Moyens d'évaluation
            for me in cap.moyens_evaluation:
                form_cap.moyens_evaluation.append_entry(me.texte)

        # Récupération des détails
        prealables_details = get_related_courses(cours_id, 'CoursPrealable', 'cours_prealable_id')
        corequisites_details = get_related_courses(cours_id, 'CoursCorequis', 'cours_corequis_id')

        # Récupération des compétences
        competences_developpees_from_cours = get_competences(cours_id, 'developpees')
        competences_atteintes = get_competences(cours_id, 'atteintes')
        elements_competence_par_cours = get_elements_competence(cours_id)

        # Rendu du template
        return render_template(
            'view_plan_cadre.html',
            cours=cours,
            plan=plan,
            prealables_details=prealables_details,
            corequisites_details=corequisites_details,
            cours_relies=plan.cours_relies,  # PlanCadreCoursRelies
            plan_form=plan_form,
            capacites_data=plan.capacites,  # Just passing them out
            generate_form=generate_form,
            import_form=import_form,
            competences_developpees_from_cours=competences_developpees_from_cours,
            competences_atteintes=competences_atteintes,
            elements_competence_par_cours=elements_competence_par_cours
        )

    # POST -> Mise à jour du plan-cadre
    elif request.method == 'POST':
        if current_user.role == 'admin':
            pass  # Admin can edit all plans
        elif current_user.role == 'coordo':
            programme_id = get_programme_id_for_cours(cours_id)
            if not programme_id or not is_coordo_for_programme(current_user.id, programme_id):
                message = "Vous n'avez pas l'autorisation de modifier ce plan-cadre car vous n'êtes pas coordonnateur de ce programme."
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': message}), 403
                flash(message, 'danger')
                return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        else:
            message = "Vous n'avez pas l'autorisation de modifier ce plan-cadre."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message}), 403
            flash(message, 'danger')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

        form_submitted = PlanCadreForm(request.form)
        if form_submitted.validate_on_submit():
            try:
                # Mettre à jour le plan-cadre principal
                plan.place_intro = form_submitted.place_intro.data
                plan.objectif_terminal = form_submitted.objectif_terminal.data
                plan.structure_intro = form_submitted.structure_intro.data
                plan.structure_activites_theoriques = form_submitted.structure_activites_theoriques.data
                plan.structure_activites_pratiques = form_submitted.structure_activites_pratiques.data
                plan.structure_activites_prevues = form_submitted.structure_activites_prevues.data
                plan.eval_evaluation_sommative = form_submitted.eval_evaluation_sommative.data
                plan.eval_nature_evaluations_sommatives = form_submitted.eval_nature_evaluations_sommatives.data
                plan.eval_evaluation_de_la_langue = form_submitted.eval_evaluation_de_la_langue.data
                plan.eval_evaluation_sommatives_apprentissages = form_submitted.eval_evaluation_sommatives_apprentissages.data

                # On supprime toutes les anciennes entrées reliées pour les recréer
                plan.competences_developpees.clear()
                plan.objets_cibles.clear()
                plan.competences_certifiees.clear()
                plan.cours_corequis.clear()
                plan.cours_prealables.clear()
                plan.cours_relies.clear()
                plan.savoirs_etre.clear()

                # competences_developpees
                seen_cdev = set()
                for entry in form_submitted.competences_developpees.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_cdev:
                        seen_cdev.add(t)
                        plan.competences_developpees.append(
                            PlanCadreCompetencesDeveloppees(texte=t, description=d)
                        )

                # objets_cibles
                seen_oc = set()
                for entry in form_submitted.objets_cibles.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_oc:
                        seen_oc.add(t)
                        plan.objets_cibles.append(
                            PlanCadreObjetsCibles(texte=t, description=d)
                        )

                # competences_certifiees
                seen_cc = set()
                for entry in form_submitted.competences_certifiees.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_cc:
                        seen_cc.add(t)
                        plan.competences_certifiees.append(
                            PlanCadreCompetencesCertifiees(texte=t, description=d)
                        )

                # cours_corequis
                seen_co = set()
                for entry in form_submitted.cours_corequis.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_co:
                        seen_co.add(t)
                        plan.cours_corequis.append(
                            PlanCadreCoursCorequis(texte=t, description=d)
                        )

                # cours_prealables
                seen_cp = set()
                for entry in form_submitted.cours_prealables.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_cp:
                        seen_cp.add(t)
                        plan.cours_prealables.append(
                            PlanCadreCoursPrealables(texte=t, description=d)
                        )

                # cours_relies
                seen_cr = set()
                for entry in form_submitted.cours_relies.entries:
                    t = entry.texte.data.strip()
                    d = entry.texte_description.data.strip() if entry.texte_description.data else None
                    if t and t not in seen_cr:
                        seen_cr.add(t)
                        plan.cours_relies.append(
                            PlanCadreCoursRelies(texte=t, description=d)
                        )

                # savoir_etre
                seen_se = set()
                for entry in form_submitted.savoir_etre.entries:
                    t = entry.texte.data.strip()
                    if t and t not in seen_se:
                        seen_se.add(t)
                        plan.savoirs_etre.append(
                            PlanCadreSavoirEtre(texte=t)
                        )

                # Gérer les capacités (et tout ce qui en dépend)
                # On va d'abord collecter les IDs existants
                existing_cap_ids = {cap.id for cap in plan.capacites}

                # Regrouper data du formulaire
                # (On détecte les indexes dans request.form)
                raw_capacite_keys = [
                    k for k in request.form.keys()
                    if k.startswith('capacites-') and k.endswith('-capacite')
                ]
                # Exemple de clé: "capacites-0-capacite"
                # On en extrait l'index: 0
                cap_indices = {int(k.split('-')[1]) for k in raw_capacite_keys}

                # Pour chaque index, on récupère les champs
                new_cap_ids_handled = set()

                for idx in sorted(cap_indices):
                    prefix = f'capacites-{idx}'
                    cap_id = request.form.get(f'{prefix}-id', "").strip()
                    capacite_value = request.form.get(f'{prefix}-capacite', "").strip()

                    if not capacite_value:
                        # Rien à faire si champ vide
                        continue

                    description_value = request.form.get(f'{prefix}-description_capacite', "").strip()
                    pmin_value = request.form.get(f'{prefix}-ponderation_min', "0")
                    pmax_value = request.form.get(f'{prefix}-ponderation_max', "100")

                    try:
                        pmin_int = int(pmin_value)
                        pmax_int = int(pmax_value)
                    except ValueError:
                        pmin_int, pmax_int = 0, 100

                    # On cherche si cap_id dans les existants
                    if cap_id and cap_id.isdigit() and int(cap_id) in existing_cap_ids:
                        # Mettre à jour la cap existante
                        existing_cap = PlanCadreCapacites.query.get(int(cap_id))
                        existing_cap.capacite = capacite_value
                        existing_cap.description_capacite = description_value
                        existing_cap.ponderation_min = pmin_int
                        existing_cap.ponderation_max = pmax_int

                        # Clear sub-lists
                        existing_cap.savoirs_necessaires.clear()
                        existing_cap.savoirs_faire.clear()
                        existing_cap.moyens_evaluation.clear()

                        # On gère ses sous-champs
                        # Savoirs nécessaires
                        sn_keys = [
                            sk for sk in request.form.keys()
                            if sk.startswith(f'{prefix}-savoirs_necessaires-')
                        ]
                        for sk in sn_keys:
                            val = request.form.get(sk, "").strip()
                            if val:
                                existing_cap.savoirs_necessaires.append(
                                    PlanCadreCapaciteSavoirsNecessaires(texte=val)
                                )

                        # Savoirs faire
                        sf_texte_keys = [
                            sfk for sfk in request.form.keys()
                            if sfk.startswith(f'{prefix}-savoirs_faire-') and sfk.endswith('-texte')
                        ]
                        for sfk in sf_texte_keys:
                            base_k = sfk[:-6]  # remove "-texte"
                            texte_val = request.form.get(sfk, "").strip()
                            if texte_val:
                                cible_val = request.form.get(f'{base_k}-cible', "").strip()
                                seuil_val = request.form.get(f'{base_k}-seuil_reussite', "").strip()
                                existing_cap.savoirs_faire.append(
                                    PlanCadreCapaciteSavoirsFaire(
                                        texte=texte_val,
                                        cible=cible_val,
                                        seuil_reussite=seuil_val
                                    )
                                )

                        # Moyens d'évaluation
                        me_keys = [
                            mk for mk in request.form.keys()
                            if mk.startswith(f'{prefix}-moyens_evaluation-') and mk.endswith('-texte')
                        ]
                        for mk in me_keys:
                            val = request.form.get(mk, "").strip()
                            if val:
                                existing_cap.moyens_evaluation.append(
                                    PlanCadreCapaciteMoyensEvaluation(texte=val)
                                )

                        new_cap_ids_handled.add(int(cap_id))

                    else:
                        # Nouvelle capacité
                        new_cap = PlanCadreCapacites(
                            capacite=capacite_value,
                            description_capacite=description_value,
                            ponderation_min=pmin_int,
                            ponderation_max=pmax_int
                        )
                        plan.capacites.append(new_cap)
                        db.session.flush()  # pour avoir un ID

                        # Savoirs nécessaires
                        sn_keys = [
                            sk for sk in request.form.keys()
                            if sk.startswith(f'{prefix}-savoirs_necessaires-')
                        ]
                        for sk in sn_keys:
                            val = request.form.get(sk, "").strip()
                            if val:
                                new_cap.savoirs_necessaires.append(
                                    PlanCadreCapaciteSavoirsNecessaires(texte=val)
                                )

                        # Savoirs faire
                        sf_texte_keys = [
                            sfk for sfk in request.form.keys()
                            if sfk.startswith(f'{prefix}-savoirs_faire-') and sfk.endswith('-texte')
                        ]
                        for sfk in sf_texte_keys:
                            base_k = sfk[:-6]
                            texte_val = request.form.get(sfk, "").strip()
                            if texte_val:
                                cible_val = request.form.get(f'{base_k}-cible', "").strip()
                                seuil_val = request.form.get(f'{base_k}-seuil_reussite', "").strip()
                                new_cap.savoirs_faire.append(
                                    PlanCadreCapaciteSavoirsFaire(
                                        texte=texte_val,
                                        cible=cible_val,
                                        seuil_reussite=seuil_val
                                    )
                                )

                        # Moyens d'évaluation
                        me_keys = [
                            mk for mk in request.form.keys()
                            if mk.startswith(f'{prefix}-moyens_evaluation-') and mk.endswith('-texte')
                        ]
                        for mk in me_keys:
                            val = request.form.get(mk, "").strip()
                            if val:
                                new_cap.moyens_evaluation.append(
                                    PlanCadreCapaciteMoyensEvaluation(texte=val)
                                )

                # Supprimer les capacités qui n'ont pas été re-soumises
                to_delete_ids = existing_cap_ids - new_cap_ids_handled
                if to_delete_ids:
                    for cid in to_delete_ids:
                        cap_to_del = PlanCadreCapacites.query.get(cid)
                        if cap_to_del:
                            db.session.delete(cap_to_del)

                plan.modified_at = datetime.utcnow()
                plan.modified_by_id = current_user.id

                db.session.commit()
                success_message = "Plan-cadre et capacités mis à jour avec succès."

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': success_message}), 200
                else:
                    flash(success_message, "success")
            except Exception as e:
                db.session.rollback()
                error_message = f"Erreur lors de la mise à jour : {str(e)}"
                print("[DEBUG] Exception in updating plan_cadre:", e)
                traceback.print_exc()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': error_message}), 500
                else:
                    flash(error_message, "danger")

        else:
            error_message = "Formulaire invalide. Veuillez vérifier vos entrées."
            print("[DEBUG] Form validation failed:", form_submitted.errors)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': error_message, 'errors': form_submitted.errors}), 400
            else:
                flash(error_message, "danger")

        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))


# --------------------------------------------------------------------------
# Route pour mettre à jour l'introduction via AJAX
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/update_intro', methods=['POST'])
@login_required
@ensure_profile_completed
def update_intro(cours_id, plan_id):
    try:
        # Validate CSRF token
        csrf_token = request.headers.get('X-CSRFToken')
        validate_csrf(csrf_token)

        data = request.get_json()
        new_intro = data.get('place_intro', '').strip()

        if not new_intro:
            return jsonify({'success': False, 'message': "Le texte de l'introduction ne peut pas être vide."}), 400

        plan = get_plan_cadre(plan_id, cours_id)
        if not plan:
            return jsonify({'success': False, 'message': "PlanCadre introuvable."}), 404

        plan.place_intro = new_intro
        db.session.commit()
        return jsonify({'success': True}), 200

    except CSRFError:
        return jsonify({'success': False, 'message': 'CSRF token invalide.'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Erreur update_intro: {str(e)}")
        return jsonify({'success': False, 'message': 'Une erreur est survenue.'}), 500


# --------------------------------------------------------------------------
# Route pour vue ou ajout direct d'un plan-cadre (si non existant)
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/plan_cadre', methods=['GET'])
@login_required
@ensure_profile_completed
def view_or_add_plan_cadre(cours_id):
    """
    Vérifie si un plan-cadre existe pour le cours. Si oui, redirige dessus.
    Sinon, crée un plan-cadre vide et redirige.
    """
    existing_plan = PlanCadre.query.filter_by(cours_id=cours_id).first()
    if existing_plan:
        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=existing_plan.id))
    else:
        # Créer un plan-cadre vide
        try:
            new_plan_cadre = PlanCadre(
                cours_id=cours_id,
                place_intro="", 
                objectif_terminal="",
                structure_intro="",
                structure_activites_theoriques="",
                structure_activites_pratiques="",
                structure_activites_prevues="",
                eval_evaluation_sommative="",
                eval_nature_evaluations_sommatives="",
                eval_evaluation_de_la_langue="",
                eval_evaluation_sommatives_apprentissages=""
            )
            db.session.add(new_plan_cadre)
            db.session.commit()
            flash('Plan-Cadre créé avec succès.', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=new_plan_cadre.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f'Erreur : {e}', 'danger')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))


# --------------------------------------------------------------------------
# Route pour visualiser un cours
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>')
@login_required
@ensure_profile_completed
def view_cours(cours_id):
    cours = Cours.query.filter_by(id=cours_id).first()
    if not cours:
        flash('Cours non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Compétences développées
    competences_developpees = (
        db.session.query(Competence)
        .join(CompetenceParCours, Competence.id == CompetenceParCours.competence_developpee_id)
        .filter(
            CompetenceParCours.cours_id == cours_id,
            CompetenceParCours.competence_developpee_id.isnot(None)
        )
        .all()
    )

    # Compétences atteintes
    competences_atteintes = (
        db.session.query(Competence)
        .join(CompetenceParCours, Competence.id == CompetenceParCours.competence_atteinte_id)
        .filter(
            CompetenceParCours.cours_id == cours_id,
            CompetenceParCours.competence_atteinte_id.isnot(None)
        )
        .all()
    )

    # Éléments de compétence par cours
    results = (
        db.session.query(ElementCompetenceParCours, ElementCompetence, Competence)
        .join(ElementCompetence, ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
        .join(Competence, ElementCompetence.competence_id == Competence.id)
        .filter(ElementCompetenceParCours.cours_id == cours_id)
        .all()
    )

    elements_competence_grouped = {}
    for ecp, ec, c in results:
        comp_id = c.id
        if comp_id not in elements_competence_grouped:
            elements_competence_grouped[comp_id] = {
                'nom': c.nom,
                'code': c.code,
                'elements': []
            }
        elements_competence_grouped[comp_id]['elements'].append({
            'element_competence_nom': ec.nom,
            'status': ecp.status
        })

    # Cours préalables
    prealables = CoursPrealable.query.filter_by(cours_id=cours_id).all()
    prealables_ids = [p.cours_prealable_id for p in prealables]
    prealables_details = []
    if prealables_ids:
        prealables_details = Cours.query.filter(Cours.id.in_(prealables_ids)).all()

    # Cours corequis
    corequisites = CoursCorequis.query.filter_by(cours_id=cours_id).all()
    corequisites_ids = [c.cours_corequis_id for c in corequisites]
    corequisites_details = []
    if corequisites_ids:
        corequisites_details = Cours.query.filter(Cours.id.in_(corequisites_ids)).all()

    # Plans-cadres du cours (un ou plusieurs selon la DB)
    plans_cadres = PlanCadre.query.filter_by(cours_id=cours_id).all()

    # Formulaires de suppression de plan-cadre
    delete_forms_plans = {}
    for pc in plans_cadres:
        delete_forms_plans[pc.id] = DeleteForm(prefix=f"plan_cadre-{pc.id}")

    # Formulaire de suppression pour le cours
    delete_form = DeleteForm(prefix=f"cours-{cours.id}")

    return render_template(
        'view_cours.html',
        cours=cours,
        plans_cadres=plans_cadres,
        competences_developpees=competences_developpees,
        competences_atteintes=competences_atteintes,
        elements_competence_par_cours=elements_competence_grouped,
        prealables_details=prealables_details,
        corequisites_details=corequisites_details,
        delete_form=delete_form,
        delete_forms_plans=delete_forms_plans
    )


# --------------------------------------------------------------------------
# Route pour éditer une capacité (EXEMPLE conservé, usage SQAlchemy direct)
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/capacite/<int:capacite_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
@ensure_profile_completed
def edit_capacite(cours_id, plan_id, capacite_id):
    form = CapaciteItemForm()

    # Récupérer plan et capacité
    plan = PlanCadre.query.filter_by(id=plan_id, cours_id=cours_id).first()
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    capacite = PlanCadreCapacites.query.filter_by(id=capacite_id, plan_cadre_id=plan_id).first()
    if not capacite:
        flash('Capacité non trouvée pour ce Plan Cadre.', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'GET':
        # Pré-remplir le formulaire
        form.capacite.data = capacite.capacite
        form.description_capacite.data = capacite.description_capacite
        form.ponderation_min.data = capacite.ponderation_min
        form.ponderation_max.data = capacite.ponderation_max

        # Vider les entrées existantes
        form.savoirs_necessaires.entries = []
        form.savoirs_faire.entries = []
        form.moyens_evaluation.entries = []

        # Ajouter les savoirs nécessaires existants
        for sn in capacite.savoirs_necessaires:
            entry_form = form.savoirs_necessaires.append_entry()
            entry_form.data = sn.texte

        # Ajouter les savoirs faire existants
        for sf in capacite.savoirs_faire:
            entry_form = form.savoirs_faire.append_entry()
            entry_form.texte.data = sf.texte
            entry_form.cible.data = sf.cible if sf.cible else ''
            entry_form.seuil_reussite.data = sf.seuil_reussite if sf.seuil_reussite else ''

        # Ajouter les moyens d'évaluation existants
        for me in capacite.moyens_evaluation:
            entry_form = form.moyens_evaluation.append_entry()
            entry_form.texte.data = me.texte

    if form.validate_on_submit():
        try:
            # Mise à jour de la capacité
            capacite.capacite = form.capacite.data.strip()
            capacite.description_capacite = form.description_capacite.data.strip()
            capacite.ponderation_min = form.ponderation_min.data
            capacite.ponderation_max = form.ponderation_max.data

            if capacite.ponderation_min > capacite.ponderation_max:
                flash('La pondération minimale ne peut pas être supérieure à la pondération maximale.', 'danger')
                return redirect(url_for('cours_bp.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

            # Supprimer les anciens
            capacite.savoirs_necessaires.clear()
            capacite.savoirs_faire.clear()
            capacite.moyens_evaluation.clear()

            # Réinsérer les savoirs nécessaires
            for sav in form.savoirs_necessaires.data:
                if sav.strip():
                    capacite.savoirs_necessaires.append(
                        PlanCadreCapaciteSavoirsNecessaires(texte=sav.strip())
                    )

            # Réinsérer les savoirs faire
            for sf_form in form.savoirs_faire.entries:
                texte_val = sf_form.texte.data.strip()
                if texte_val:
                    cible_val = sf_form.cible.data.strip() if sf_form.cible.data else None
                    seuil_val = sf_form.seuil_reussite.data.strip() if sf_form.seuil_reussite.data else None
                    capacite.savoirs_faire.append(
                        PlanCadreCapaciteSavoirsFaire(
                            texte=texte_val,
                            cible=cible_val,
                            seuil_reussite=seuil_val
                        )
                    )

            # Réinsérer les moyens d'évaluation
            for me_form in form.moyens_evaluation.entries:
                val = me_form.texte.data.strip()
                if val:
                    capacite.moyens_evaluation.append(
                        PlanCadreCapaciteMoyensEvaluation(texte=val)
                    )

            db.session.commit()
            flash('Capacité mise à jour avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de la capacité : {e}', 'danger')
            return redirect(url_for('cours_bp.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

    return render_template(
        'edit_capacite.html',
        form=form,
        plan_id=plan_id,
        capacite_id=capacite_id,
        cours_id=cours_id
    )


# --------------------------------------------------------------------------
# Nouvelle Route pour Supprimer un Cours
# --------------------------------------------------------------------------
@cours_bp.route('/<int:cours_id>/delete', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def delete_cours(cours_id):
    form = DeleteForm(prefix=f"cours-{cours_id}")
    if form.validate_on_submit():
        cours = Cours.query.get(cours_id)
        if not cours:
            flash('Cours non trouvé.')
            return redirect(url_for('main.index'))
        programme_id = cours.programme_id

        try:
            db.session.delete(cours)
            db.session.commit()
            flash('Cours supprimé avec succès!')
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f'Erreur lors de la suppression du cours : {e}')
        return redirect(url_for('main.view_programme', programme_id=programme_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.')
        return redirect(url_for('main.index'))
