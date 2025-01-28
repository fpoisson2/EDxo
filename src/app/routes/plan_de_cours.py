from flask import current_app, Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from app.models import (
    db, Cours, PlanCadre, PlanCadreCapacites, PlanCadreSavoirEtre,
    PlanDeCours, PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
    PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations, PlanDeCoursEvaluationsCapacites, Programme
)
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from app.forms import PlanDeCoursForm
import os
from docxtpl import DocxTemplate
import io
from flask import send_file
import markdown
from sqlalchemy import func
from bs4 import BeautifulSoup
import zipfile
from datetime import datetime
from utils.utils import get_initials, get_programme_id_for_cours, is_teacher_in_programme
from pathlib import Path

# Définir le chemin de base de l'application
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



def parse_markdown_nested(md_text):
    """
    Converts Markdown text into a nested list of dictionaries where bullet points
    are treat ed as children of their preceding paragraph.
    Each dictionary has 'text' and 'children' keys.
    
    Example input:
    This is a top level text
    - First bullet (becomes child of above text)
      - Nested bullet
    Another top level text
    - Second bullet (becomes child of second text)
    
    Returns a list of dictionaries representing the nested structure.
    """
    # Ensure proper spacing for markdown list processing
    md_text = md_text.replace('\n- ', '\n\n- ')  # Add extra newline before list items
    html = markdown.markdown(md_text)
    soup = BeautifulSoup(html, 'html.parser')
    
    def parse_list(ul):
        items = []
        for li in ul.find_all('li', recursive=False):
            item_text = ''
            children = []
            # Extract text and check for nested <ul>
            for content in li.contents:
                if isinstance(content, str):
                    item_text += content.strip()
                elif content.name == 'ul':
                    children = parse_list(content)
                elif content.name == 'p':
                    item_text += content.get_text().strip()
            items.append({'text': item_text, 'children': children})
        return items

    nested_structure = []
    current_parent = None
    
    # Process all top-level elements
    for element in soup.find_all(['p', 'ul'], recursive=False):
        if element.name == 'p':
            # Create new top-level item
            text = element.get_text().strip()
            if text:
                current_parent = {'text': text, 'children': []}
                nested_structure.append(current_parent)
        elif element.name == 'ul' and current_parent is not None:
            # Add bullet points as children of the current parent
            current_parent['children'].extend(parse_list(element))
        elif element.name == 'ul':
            # Handle case where there's no preceding paragraph
            nested_structure.extend(parse_list(element))
    
    return nested_structure


plan_de_cours_bp = Blueprint("plan_de_cours", __name__, template_folder="templates")

@plan_de_cours_bp.route(
    "/cours/<int:cours_id>/plan_de_cours/", methods=["GET", "POST"]
)
@plan_de_cours_bp.route(
    "/cours/<int:cours_id>/plan_de_cours/<string:session>/", methods=["GET", "POST"]
)
@login_required
def view_plan_de_cours(cours_id, session=None):
    # 1. Récupération du Cours
    cours = db.session.get(Cours, cours_id)
    if not cours:
        abort(404, description="Cours non trouvé.")

    plan_cadre = PlanCadre.query.options(
        db.joinedload(PlanCadre.capacites),
        db.joinedload(PlanCadre.savoirs_etre)
    ).filter_by(cours_id=cours_id).first()

    if not plan_cadre:
        flash("Aucun PlanCadre associé à ce cours.", "warning")
        return redirect(url_for('programme.view_programme', programme_id=cours.programme_id))

    # 3. Détermination du PlanDeCours à utiliser
    if session:
        plan_de_cours = PlanDeCours.query.filter_by(cours_id=cours.id, session=session).first()
        if not plan_de_cours:
            plan_de_cours = PlanDeCours(cours_id=cours.id, session=session)
            db.session.add(plan_de_cours)
            db.session.commit()
            flash(f"Plan de Cours pour la session {session} créé.", "success")
    else:
        plan_de_cours = PlanDeCours.query.filter_by(cours_id=cours.id).order_by(PlanDeCours.id.desc()).first()
        if not plan_de_cours:
            flash("Aucun Plan de Cours existant. Création d'un nouveau Plan de Cours.", "warning")
            plan_de_cours = PlanDeCours(cours_id=cours.id, session="À définir")
            db.session.add(plan_de_cours)
            db.session.commit()
            flash("Nouveau Plan de Cours créé. Veuillez le remplir.", "success")

    programme = cours.programme
    departement = programme.department
    regles_departementales = departement.regles  # Règles départementales
    regles_piea = departement.piea  # Règles de PIEA

    # 4. Préparer le formulaire
    form = PlanDeCoursForm()

    if request.method == "GET":
        # 4.1. Initialiser les Champs Simples
        form.campus.data = plan_de_cours.campus
        form.session.data = plan_de_cours.session
        form.presentation_du_cours.data = plan_de_cours.presentation_du_cours
        form.objectif_terminal_du_cours.data = plan_de_cours.objectif_terminal_du_cours
        form.organisation_et_methodes.data = plan_de_cours.organisation_et_methodes
        form.accomodement.data = plan_de_cours.accomodement
        form.evaluation_formative_apprentissages.data = plan_de_cours.evaluation_formative_apprentissages
        form.evaluation_expression_francais.data = plan_de_cours.evaluation_expression_francais
        form.seuil_reussite.data = plan_de_cours.seuil_reussite

        # 4.2. Initialiser les Informations de l’Enseignant
        form.nom_enseignant.data = plan_de_cours.nom_enseignant
        form.telephone_enseignant.data = plan_de_cours.telephone_enseignant
        form.courriel_enseignant.data = plan_de_cours.courriel_enseignant
        form.bureau_enseignant.data = plan_de_cours.bureau_enseignant

        form.materiel.data = plan_de_cours.materiel

        # 4.3. Initialiser les FieldLists

        # Calendriers
        if plan_de_cours.calendriers:
            for cal in plan_de_cours.calendriers:
                form.calendriers.append_entry({
                    "semaine": cal.semaine,
                    "sujet": cal.sujet,
                    "activites": cal.activites,
                    "travaux_hors_classe": cal.travaux_hors_classe,
                    "evaluations": cal.evaluations
                })

        # Médiagraphies
        if plan_de_cours.mediagraphies:
            for med in plan_de_cours.mediagraphies:
                form.mediagraphies.append_entry({"reference_bibliographique": med.reference_bibliographique})

        # Disponibilités
        if plan_de_cours.disponibilites:
            for disp in plan_de_cours.disponibilites:
                form.disponibilites.append_entry({
                    "jour_semaine": disp.jour_semaine,
                    "plage_horaire": disp.plage_horaire,
                    "lieu": disp.lieu
                })

        # Évaluations
        if plan_de_cours.evaluations:
            for ev in plan_de_cours.evaluations:
                eval_entry = {
                    "titre_evaluation": ev.titre_evaluation,
                    "texte_description": ev.description,
                    "semaine": ev.semaine,
                    "capacites": []
                }
                for cap_link in ev.capacites:
                    eval_entry["capacites"].append({
                        "capacite_id": cap_link.capacite_id,
                        "ponderation": cap_link.ponderation
                    })
                form.evaluations.append_entry(eval_entry)

            # 4.4. Assigner les choices pour chaque capacite_id dans le GET
            choices_capacites = [(c.id, c.capacite) for c in plan_cadre.capacites]
            if choices_capacites:
                for eval_f in form.evaluations:
                    for cap_f in eval_f.capacites:
                        cap_f.capacite_id.choices = choices_capacites
            else:
                # Si aucune capacité n'est définie, désactiver ou masquer les champs capacite_id
                for eval_f in form.evaluations:
                    for cap_f in eval_f.capacites:
                        cap_f.capacite_id.choices = []
                        cap_f.capacite_id.render_kw = {'disabled': True}  # Optionnel: rendre le champ désactivé

    # 5. Traitement du POST (sauvegarde)
    if request.method == "POST":
        programme_id = get_programme_id_for_cours(cours_id)
        if current_user.role not in ['admin', 'coordo']:
            # Si l'utilisateur est enseignant, vérifier l'association avec le programme
            if current_user.role == 'professeur':
                if not is_teacher_in_programme(current_user.id, programme_id):
                    abort(403, description="Accès interdit aux plans de cours de ce programme.")
            else:
                abort(403, description="Rôle utilisateur non autorisé.")
        # Vérifier si c'est une requête AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # (1) Assigner les choices avant validation
        choices_capacites = [(c.id, c.capacite) for c in plan_cadre.capacites]
        for eval_f in form.evaluations:
            for cap_f in eval_f.capacites:
                cap_f.capacite_id.choices = choices_capacites

        # (2) Maintenant on peut valider
        if form.validate_on_submit():
            try:
                with db.session.no_autoflush:
                    # 5.1. Mettre à jour les Champs Simples
                    plan_de_cours.campus = form.campus.data
                    plan_de_cours.session = form.session.data
                    plan_de_cours.presentation_du_cours = form.presentation_du_cours.data
                    plan_de_cours.objectif_terminal_du_cours = form.objectif_terminal_du_cours.data
                    plan_de_cours.organisation_et_methodes = form.organisation_et_methodes.data
                    plan_de_cours.accomodement = form.accomodement.data
                    plan_de_cours.evaluation_formative_apprentissages = form.evaluation_formative_apprentissages.data
                    plan_de_cours.evaluation_expression_francais = form.evaluation_expression_francais.data
                    plan_de_cours.seuil_reussite = form.seuil_reussite.data

                    # 5.2. Mettre à jour les Informations de l’Enseignant
                    plan_de_cours.nom_enseignant = form.nom_enseignant.data
                    plan_de_cours.telephone_enseignant = form.telephone_enseignant.data
                    plan_de_cours.courriel_enseignant = form.courriel_enseignant.data
                    plan_de_cours.bureau_enseignant = form.bureau_enseignant.data

                    plan_de_cours.materiel = form.materiel.data

                    # 5.3. Gérer les FieldLists

                    # Calendriers
                    plan_de_cours.calendriers.clear()
                    for cal_f in form.calendriers.entries:
                        new_cal = PlanDeCoursCalendrier(
                            semaine=cal_f.data.get("semaine"),
                            sujet=cal_f.data.get("sujet"),
                            activites=cal_f.data.get("activites"),
                            travaux_hors_classe=cal_f.data.get("travaux_hors_classe"),
                            evaluations=cal_f.data.get("evaluations")
                        )
                        plan_de_cours.calendriers.append(new_cal)

                    # Médiagraphies
                    plan_de_cours.mediagraphies.clear()
                    for med_f in form.mediagraphies.entries:
                        new_med = PlanDeCoursMediagraphie(
                            reference_bibliographique=med_f.data.get("reference_bibliographique")
                        )
                        plan_de_cours.mediagraphies.append(new_med)

                    # Disponibilités
                    plan_de_cours.disponibilites.clear()
                    for disp_f in form.disponibilites.entries:
                        new_disp = PlanDeCoursDisponibiliteEnseignant(
                            jour_semaine=disp_f.data.get("jour_semaine"),
                            plage_horaire=disp_f.data.get("plage_horaire"),
                            lieu=disp_f.data.get("lieu")
                        )
                        plan_de_cours.disponibilites.append(new_disp)

                    # Évaluations
                    plan_de_cours.evaluations.clear()
                    for ev_f in form.evaluations.entries:
                        # 1) Créer l'évaluation
                        new_ev = PlanDeCoursEvaluations(
                            titre_evaluation=ev_f.data.get("titre_evaluation"),
                            description=ev_f.data.get("texte_description"),
                            semaine=ev_f.data.get("semaine")
                        )
                        plan_de_cours.evaluations.append(new_ev)
                        
                        # 2) Créer les liaisons (capacités + ponderation) seulement s'il y a des capacités
                        if ev_f.capacites.entries:
                            for cap_f in ev_f.capacites.entries:
                                cap_link = PlanDeCoursEvaluationsCapacites(
                                    evaluation=new_ev,
                                    capacite_id=cap_f.data.get("capacite_id"),
                                    ponderation=cap_f.data.get("ponderation")
                                )
                                new_ev.capacites.append(cap_link)

                # 5.4. Commit des Changements
                db.session.commit()
                
                if is_ajax:
                    return jsonify({
                        'success': True,
                        'message': 'Le plan de cours a été mis à jour avec succès!'
                    })
                else:
                    flash("Le plan de cours a été mis à jour avec succès!", "success")
                    return redirect(url_for("plan_de_cours.view_plan_de_cours",
                                        cours_id=cours.id,
                                        session=plan_de_cours.session))
                                        
            except Exception as e:
                db.session.rollback()
                error_message = str(e)
                if is_ajax:
                    return jsonify({
                        'success': False,
                        'message': f"Erreur lors de la mise à jour du plan de cours: {error_message}"
                    }), 400
                else:
                    flash(f"Erreur lors de la mise à jour du plan de cours: {error_message}", "danger")
        else:
            if is_ajax:
                return jsonify({
                    'success': False,
                    'message': "Erreur de validation du formulaire",
                    'errors': form.errors
                }), 400

    # 6. Rendre la page
    return render_template("view_plan_de_cours.html",
                                        cours=cours, 
                                        plan_cadre=plan_cadre,
                                        plan_de_cours=plan_de_cours,
                                        form=form,
                                        departement=departement,
                                        regles_departementales=regles_departementales,
                                        regles_piea=regles_piea)


@plan_de_cours_bp.route(
    "/export_session_plans/<int:programme_id>/<string:session>", 
    methods=["GET"]
)
@login_required
def export_session_plans(programme_id, session):
    """
    Exporte tous les plans de cours d'une session donnée dans un fichier ZIP
    """

    programme = Programme.query.get_or_404(programme_id)
    # Convertir le numéro de session en format attendu (ex: 2 -> h25 ou a24)
    session_num = int(session)
    current_year = datetime.now().year % 100  # Obtenir les 2 derniers chiffres de l'année
    
    # Pour les sessions paires (2,4,6), on utilise l'année suivante car c'est l'hiver
    if session_num % 2 == 0:  
        session_code = f"H{current_year}"  # Session d'hiver de l'année suivante
    else:
        session_code = f"A{current_year}"  # Session d'automne de l'année courante

    # Créer un buffer en mémoire pour le fichier ZIP
    memory_file = io.BytesIO()
    
    # Créer l'archive ZIP
    with zipfile.ZipFile(memory_file, 'w') as zf:
        # Récupérer tous les plans de cours de la session
        plans_de_cours = PlanDeCours.query.join(Cours).filter(
            PlanDeCours.session == session_code,
            Cours.programme_id == programme_id,
            func.substr(Cours.code, 5, 1) == str(session_num)  # Position 5, longueur 1
        ).all()

        filtered_plans = []
        for plan_de_cours in plans_de_cours:
            cours = Cours.query.get_or_404(plan_de_cours.cours_id)
            try:
                session_cours = int(cours.code[0])
                if session_cours == session_num:
                    filtered_plans.append(plan_de_cours)
            except ValueError:
                print(f"Warning: Code de cours invalide: {cours.code}")
                continue

        # Utiliser filtered_plans au lieu de plans_de_cours pour la suite
        plans_de_cours = filtered_plans

        if not plans_de_cours:
            flash(f"Aucun plan de cours trouvé pour la session {session}.", "warning")
            return redirect(url_for('main.index'))
            
        # Pour chaque plan de cours
        for plan_de_cours in plans_de_cours:
            # Récupérer le cours associé
            cours = Cours.query.get_or_404(plan_de_cours.cours_id)
            
            # Récupérer le plan cadre
            plan_cadre = PlanCadre.query.options(
                db.joinedload(PlanCadre.capacites),
                db.joinedload(PlanCadre.savoirs_etre)
            ).filter_by(cours_id=cours.id).first()
            
            if not plan_cadre:
                continue
                
            # Récupérer les autres informations nécessaires
            programme = cours.programme
            departement = programme.department if programme else None
            regles_departementales = departement.regles if departement else []
            regles_piea = departement.piea if departement else []
            
            # Charger le template Word
            template_path = os.path.join(os.path.dirname(current_app.root_path), 'static', 'docs', 'plan_de_cours_template.docx')
            doc = DocxTemplate(template_path)
            
            # Préparer les données pour le tableau croisé
            all_caps = []
            cap_total_map = {}
            cap_id_total_map = {}
            
            # Maintenir l'ordre du plan cadre
            for cap in plan_cadre.capacites:
                all_caps.append(cap.capacite)
                cap_total_map[cap.capacite] = 0.0
                cap_id_total_map[cap.id] = 0.0
                
            # Calculer les totaux
            for ev in plan_de_cours.evaluations:
                for cap_link in ev.capacites:
                    cap_name = cap_link.capacite.capacite
                    cap_id = cap_link.capacite_id
                    
                    try:
                        ponderation_str = str(cap_link.ponderation).strip().replace('%', '')
                        ponderation_value = float(ponderation_str) if ponderation_str else 0.0
                        cap_total_map[cap_name] += ponderation_value
                        cap_id_total_map[cap_id] += ponderation_value
                    except (ValueError, TypeError) as e:
                        print(f"Warning: Invalid ponderation value for {cap_name}: {str(e)}")
            
            # Nettoyer les maps de totaux
            cleaned_cap_total_map = {cap: f"{total:.1f}" for cap, total in cap_total_map.items()}
            cleaned_cap_id_total_map = {cap_id: f"{total:.1f}" for cap_id, total in cap_id_total_map.items()}
            
            # Attacher la pondération totale à chaque capacité
            for capacite in plan_cadre.capacites:
                capacite.total_ponderation = cleaned_cap_id_total_map.get(capacite.id, "0.0")
            
            # Créer la map capacité-pondération pour chaque évaluation
            for ev in plan_de_cours.evaluations:
                cap_map = {cap: "" for cap in all_caps}
                for cap_link in ev.capacites:
                    cap_name = cap_link.capacite.capacite
                    ponderation_str = str(cap_link.ponderation).strip().replace('%', '')
                    try:
                        value = float(ponderation_str)
                        cap_map[cap_name] = f"{value:.1f}"
                    except (ValueError, TypeError):
                        cap_map[cap_name] = "0.0"
                ev.cap_map = cap_map
            
            # Traiter les contenus markdown
            for piea in regles_piea:
                bullet_points = parse_markdown_nested(piea.contenu)
                setattr(piea, 'bullet_points', bullet_points)
            
            for regle in regles_departementales:
                bullet_points = parse_markdown_nested(regle.contenu)
                setattr(regle, 'bullet_points', bullet_points)
            
            if plan_de_cours.evaluation_formative_apprentissages:
                bullet_points = parse_markdown_nested(plan_de_cours.evaluation_formative_apprentissages)
                setattr(plan_de_cours, 'evaluation_formative_apprentissages_bullet_points', bullet_points)
            
            if plan_de_cours.accomodement:
                bullet_points = parse_markdown_nested(plan_de_cours.accomodement)
                setattr(plan_de_cours, 'accomodement_bullet_points', bullet_points)
            
            if plan_de_cours.objectif_terminal_du_cours:
                bullet_points = parse_markdown_nested(plan_de_cours.objectif_terminal_du_cours)
                setattr(plan_de_cours, 'objectif_terminal_bullet_points', bullet_points)
            
            # Construire le contexte
            context = {
                "cours": cours,
                "plan_cadre": plan_cadre,
                "programme": programme,
                "departement": departement,
                "savoirs_etre": plan_cadre.savoirs_etre,
                "capacites_plan_cadre": plan_cadre.capacites,
                "cap_id_total_map": cleaned_cap_id_total_map,
                "plan_de_cours": plan_de_cours,
                "campus": plan_de_cours.campus,
                "session": plan_de_cours.session,
                "presentation_du_cours": plan_de_cours.presentation_du_cours,
                "objectif_terminal_du_cours": plan_de_cours.objectif_terminal_du_cours,
                "objectif_terminal_bullet_points": getattr(plan_de_cours, 'objectif_terminal_bullet_points', []),
                "organisation_et_methodes": plan_de_cours.organisation_et_methodes,
                "accomodement": plan_de_cours.accomodement,
                "accomodement_bullet_points": getattr(plan_de_cours, 'accomodement_bullet_points', []),
                "evaluation_formative_apprentissages": plan_de_cours.evaluation_formative_apprentissages,
                "evaluation_formative_apprentissages_bullet_points": getattr(plan_de_cours, 'evaluation_formative_apprentissages_bullet_points', []),
                "evaluation_expression_francais": plan_de_cours.evaluation_expression_francais,
                "seuil_reussite": plan_de_cours.seuil_reussite,
                "nom_enseignant": plan_de_cours.nom_enseignant,
                "telephone_enseignant": plan_de_cours.telephone_enseignant,
                "courriel_enseignant": plan_de_cours.courriel_enseignant,
                "bureau_enseignant": plan_de_cours.bureau_enseignant,
                "materiel": plan_de_cours.materiel,
                "calendriers": plan_de_cours.calendriers,
                "mediagraphies": plan_de_cours.mediagraphies,
                "disponibilites": plan_de_cours.disponibilites,
                "evaluations": plan_de_cours.evaluations,
                "all_caps": all_caps,
                "cap_total_map": cleaned_cap_total_map,
                "regles_departementales": regles_departementales,
                "regles_piea": regles_piea
            }
            
            # Générer le document Word
            doc.render(context)
            
            # Sauvegarder le document dans le ZIP
            doc_bytes = io.BytesIO()
            doc.save(doc_bytes)
            doc_bytes.seek(0)

            nom_enseignant = context['nom_enseignant']
            initiales = get_initials(nom_enseignant)

            
            

            # Nouveau nom de fichier avec les initiales
            filename = f"Plan_de_cours_{cours.code}_{session_code}_{initiales}.docx"
            zf.writestr(filename, doc_bytes.getvalue())
    
    # Préparer le fichier ZIP pour l'envoi
    memory_file.seek(0)
    
    return send_file(
            memory_file,
            download_name=f"Plans_de_cours_{programme.nom}_{session_code}.zip",
            as_attachment=True,
            mimetype='application/zip'
        )


@plan_de_cours_bp.route(
    "/cours/<int:cours_id>/plan_de_cours/<string:session>/export_docx", 
    methods=["GET"]
)
@login_required
def export_docx(cours_id, session):
    # 1. Récupérer le Cours
    cours = Cours.query.get_or_404(cours_id)

    # 2. Récupérer le PlanCadre + chargement des relations
    plan_cadre = PlanCadre.query.options(
        db.joinedload(PlanCadre.capacites),
        db.joinedload(PlanCadre.savoirs_etre)
    ).filter_by(cours_id=cours.id).first()

    if not plan_cadre:
        flash("Aucun PlanCadre associé à ce cours.", "warning")
        return redirect(url_for('programme.view_programme', programme_id=cours.programme_id))

    # 3. Récupérer le PlanDeCours correspondant à la session demandée
    plan_de_cours = PlanDeCours.query.filter_by(cours_id=cours.id, session=session).first()
    if not plan_de_cours:
        flash(f"Aucun PlanDeCours pour la session {session}.", "warning")
        return redirect(url_for('plan_de_cours.view_plan_de_cours', cours_id=cours.id))

    # 4. Récupérer d'autres informations (programme, département, règles, etc.)
    programme = cours.programme
    departement = programme.department if programme else None
    regles_departementales = departement.regles if departement else []
    regles_piea = departement.piea if departement else []

    # 5. Charger le template Word avec le chemin absolu
    base_path = Path(__file__).parent.parent.parent  # remonte de 3 niveaux: de routes/ vers app/ vers src/ vers edxo-dev/
    template_path = os.path.join(base_path, 'src', 'static', 'docs', 'plan_de_cours_template.docx')
    
    # Log pour debug
    current_app.logger.info(f"Looking for template at: {template_path}")
    
    if not os.path.exists(template_path):
        current_app.logger.error(f"Template not found at: {template_path}")
        flash("Erreur: Le template de plan de cours est introuvable.", "error")
        return redirect(url_for('plan_de_cours.view_plan_de_cours', cours_id=cours_id))

    doc = DocxTemplate(template_path)

    # 6. Prepare Data for Pivot Table

    # Remplacer la section de création all_caps par:
    all_caps = []
    cap_total_map = {}
    cap_id_total_map = {}

    # Maintenir l'ordre du plan cadre
    for cap in plan_cadre.capacites:
        all_caps.append(cap.capacite)
        cap_total_map[cap.capacite] = 0.0
        cap_id_total_map[cap.id] = 0.0

    # Calculer les totaux
    for ev in plan_de_cours.evaluations:
        for cap_link in ev.capacites:
            cap_name = cap_link.capacite.capacite
            cap_id = cap_link.capacite_id
            
            try:
                ponderation_str = str(cap_link.ponderation).strip().replace('%', '')
                ponderation_value = float(ponderation_str) if ponderation_str else 0.0
                cap_total_map[cap_name] += ponderation_value
                cap_id_total_map[cap_id] += ponderation_value
            except (ValueError, TypeError) as e:
                print(f"Warning: Invalid ponderation value for {cap_name}: {str(e)}")

    #all_caps = sorted(all_caps)  # Sort for consistent ordering

    # Clean up the total maps to ensure they're formatted properly for the template
    cleaned_cap_total_map = {cap: f"{total:.1f}" for cap, total in cap_total_map.items()}
    cleaned_cap_id_total_map = {cap_id: f"{total:.1f}" for cap_id, total in cap_id_total_map.items()}

    # Attach total ponderation to each capacite in capacites_plan_cadre
    for capacite in plan_cadre.capacites:
        capacite.total_ponderation = cleaned_cap_id_total_map.get(capacite.id, "0.0")

    # b. Create a capacity to ponderation map for each evaluation
    for ev in plan_de_cours.evaluations:
        cap_map = {cap: "" for cap in all_caps}
        for cap_link in ev.capacites:
            cap_name = cap_link.capacite.capacite
            # Strip the % if it exists and ensure it's properly formatted
            ponderation_str = str(cap_link.ponderation).strip().replace('%', '')
            try:
                value = float(ponderation_str)
                cap_map[cap_name] = f"{value:.1f}"
            except (ValueError, TypeError):
                cap_map[cap_name] = "0.0"
        ev.cap_map = cap_map


    for piea in regles_piea:
        # Access 'contenu' using dot notation
        bullet_points = parse_markdown_nested(piea.contenu)
        
        # Assign 'bullet_points' as a new attribute
        setattr(piea, 'bullet_points', bullet_points)

    for regle in regles_departementales:
        # Access 'contenu' using dot notation
        bullet_points = parse_markdown_nested(regle.contenu)
        
        # Assign 'bullet_points' as a new attribute
        setattr(regle, 'bullet_points', bullet_points)

    if plan_de_cours.evaluation_formative_apprentissages:
        bullet_points = parse_markdown_nested(plan_de_cours.evaluation_formative_apprentissages)
        setattr(plan_de_cours, 'evaluation_formative_apprentissages_bullet_points', bullet_points)

    # Parse bullet points for accomodement
    if plan_de_cours.accomodement:
        bullet_points = parse_markdown_nested(plan_de_cours.accomodement)
        setattr(plan_de_cours, 'accomodement_bullet_points', bullet_points)

    # Parse bullet points for objectif_terminal_du_cours
    if plan_de_cours.objectif_terminal_du_cours:
        bullet_points = parse_markdown_nested(plan_de_cours.objectif_terminal_du_cours)
        setattr(plan_de_cours, 'objectif_terminal_bullet_points', bullet_points)

    # 6. Construire le contexte pour injection (tous les champs possibles)
    context = {
        # -- Informations sur le Cours & PlanCadre
        "cours": cours,
        "plan_cadre": plan_cadre,
        "programme": programme,
        "departement": departement,
        "savoirs_etre": plan_cadre.savoirs_etre,
        "capacites_plan_cadre": plan_cadre.capacites,
        "cap_id_total_map": cleaned_cap_id_total_map,

        # -- Informations PlanDeCours
        "plan_de_cours": plan_de_cours,
        "campus": plan_de_cours.campus,
        "session": plan_de_cours.session,
        "presentation_du_cours": plan_de_cours.presentation_du_cours,
        "objectif_terminal_du_cours": plan_de_cours.objectif_terminal_du_cours,
        "objectif_terminal_bullet_points": getattr(plan_de_cours, 'objectif_terminal_bullet_points', []),
        "organisation_et_methodes": plan_de_cours.organisation_et_methodes,
        "accomodement": plan_de_cours.accomodement,
        "accomodement_bullet_points": getattr(plan_de_cours, 'accomodement_bullet_points', []),
        "evaluation_formative_apprentissages": plan_de_cours.evaluation_formative_apprentissages,
        "evaluation_formative_apprentissages_bullet_points": getattr(plan_de_cours, 'evaluation_formative_apprentissages_bullet_points', []),
        "evaluation_expression_francais": plan_de_cours.evaluation_expression_francais,
        "seuil_reussite": plan_de_cours.seuil_reussite,
        
        # -- Informations Enseignant
        "nom_enseignant": plan_de_cours.nom_enseignant,
        "telephone_enseignant": plan_de_cours.telephone_enseignant,
        "courriel_enseignant": plan_de_cours.courriel_enseignant,
        "bureau_enseignant": plan_de_cours.bureau_enseignant,

    
        "materiel": plan_de_cours.materiel,

        # -- Calendrier, Médiagraphies, Disponibilités, Évaluations
        "calendriers": plan_de_cours.calendriers,
        "mediagraphies": plan_de_cours.mediagraphies,
        "disponibilites": plan_de_cours.disponibilites,
        "evaluations": plan_de_cours.evaluations,

        # -- Evaluations Data for Pivot Table
        "all_caps": all_caps,
        "evaluations": plan_de_cours.evaluations,
        "cap_total_map": cleaned_cap_total_map,

        # -- Règles
        "regles_departementales": regles_departementales,
        "regles_piea": regles_piea
    }

    # 7. Rendre le document avec le context
    doc.render(context)

    # 8. Retourner le document (pour téléchargement) via un flux en mémoire
    byte_io = io.BytesIO()
    doc.save(byte_io)
    byte_io.seek(0)

    # 9. Envoyer le fichier .docx
    #    Selon votre version de Flask, 'attachment_filename' peut être remplacé par 'download_name'
    filename = f"Plan_de_cours_{cours.code}_{session}.docx"
    return send_file(
        byte_io,
        download_name=filename,
        as_attachment=True
    )
