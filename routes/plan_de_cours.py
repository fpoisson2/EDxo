from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from models import (db, Cours, PlanCadre, PlanCadreCapacites, PlanCadreSavoirEtre,
                   PlanDeCours,
                   PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
                   PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations)
from forms import PlanDeCoursForm

plan_de_cours_bp = Blueprint("plan_de_cours", __name__, template_folder="templates")

@plan_de_cours_bp.route(
    "/cours/<int:cours_id>/plan_de_cours/", methods=["GET", "POST"]
)
@plan_de_cours_bp.route(
    "/cours/<int:cours_id>/plan_de_cours/<string:session>/", methods=["GET", "POST"]
)
def view_plan_de_cours(cours_id, session=None):
    """
    Affiche :
     - le PlanCadre en lecture seule (place_intro, capacités, savoir-être, moyens d'évaluation)
     - le PlanDeCours en mode édition (campus, session, présentation, objectifs, organisation, etc.)
     
    Si `session` n'est pas spécifiée, affiche le PlanDeCours le plus récent.
    Si aucun PlanDeCours n'existe pour une session donnée, crée-en un nouveau vide.
    """
    # 1. Récupération du Cours
    cours = Cours.query.get(cours_id)
    if not cours:
        abort(404, description="Cours non trouvé.")

    plan_cadre = PlanCadre.query.options(
        db.joinedload(PlanCadre.capacites),
        db.joinedload(PlanCadre.savoirs_etre)
    ).filter_by(cours_id=cours_id).first()

    if not plan_cadre:
        flash("Aucun PlanCadre associé à ce cours.", "warning")
        return redirect(url_for('main.view_programme', programme_id=cours.programme_id))

    # 3. Détermination du PlanDeCours à utiliser
    if session:
        # Tenter de récupérer le PlanDeCours pour le cours et la session spécifiés
        plan_de_cours = PlanDeCours.query.filter_by(cours_id=cours.id, session=session).first()
        if not plan_de_cours:
            # Créer un nouveau PlanDeCours pour la session spécifiée
            plan_de_cours = PlanDeCours(cours_id=cours.id, session=session)
            db.session.add(plan_de_cours)
            db.session.commit()
            flash(f"Plan de Cours pour la session {session} créé.", "success")
    else:
        # Récupérer le PlanDeCours le plus récent
        plan_de_cours = PlanDeCours.query.filter_by(cours_id=cours.id).order_by(PlanDeCours.id.desc()).first()
        if not plan_de_cours:
            flash("Aucun Plan de Cours existant. Création d'un nouveau Plan de Cours.", "warning")
            # Créer un nouveau PlanDeCours avec une session par défaut
            plan_de_cours = PlanDeCours(cours_id=cours.id, session="À définir")
            db.session.add(plan_de_cours)
            db.session.commit()
            flash("Nouveau Plan de Cours créé. Veuillez le remplir.", "success")

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
                form.evaluations.append_entry({
                    "titre_evaluation": ev.titre_evaluation,
                    "texte_description": ev.description,
                    "semaine": ev.semaine,
                    "ponderation": ev.ponderation
                })

    # 5. Traitement du POST (sauvegarde)
    if request.method == "POST" and form.validate_on_submit():
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
                    new_ev = PlanDeCoursEvaluations(
                        titre_evaluation=ev_f.data.get("titre_evaluation"),
                        description=ev_f.data.get("texte_description"),
                        semaine=ev_f.data.get("semaine"),
                        ponderation=ev_f.data.get("ponderation")
                    )
                    plan_de_cours.evaluations.append(new_ev)

            # 5.4. Commit des Changements
            db.session.commit()
            # db.session.close()  # <--- Remove this line
            flash("Le PlanDeCours a été mis à jour avec succès!", "success")
            return redirect(url_for("plan_de_cours.view_plan_de_cours",
                                    cours_id=cours.id,
                                    session=plan_de_cours.session))
        except Exception as e:
            db.session.rollback()
            # db.session.close()  # <--- Remove this line
            flash(f"Erreur lors de la mise à jour du PlanDeCours: {str(e)}", "danger")

    # 6. Rendre la page
    return render_template("view_plan_de_cours.html",
                           cours=cours, 
                           plan_cadre=plan_cadre,
                           plan_de_cours=plan_de_cours,
                           form=form)
