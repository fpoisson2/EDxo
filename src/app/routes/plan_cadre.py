# plan_de_cours.py
import logging
import traceback

from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, jsonify, session
from flask_login import login_required, current_user

from utils.openai_pricing import calculate_call_cost

from openai import OpenAI

from app.forms import (
    DeleteForm,
    PlanCadreForm,
    GenerateContentForm
)
# Import SQLAlchemy DB and models
from app.models import (
    db,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees
)
from utils.decorator import role_required, roles_required, ensure_profile_completed
from utils.utils import (
    generate_docx_with_template,
    # Note: remove if no longer needed: get_db_connection
)

###############################################################################
# Configuration Logging
###############################################################################
logging.basicConfig(
    level=logging.ERROR,
    filename='app_errors.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

###############################################################################
# Blueprint
###############################################################################
plan_cadre_bp = Blueprint('plan_cadre', __name__, url_prefix='/plan_cadre')

@plan_cadre_bp.route('/<int:plan_id>/ai_generate_field', methods=['GET'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def ai_generate_field(plan_id):
    """
    SSE endpoint for AI generation of a single field in the plan-cadre.
    Must be GET, because EventSource only does GET.
    """
    import logging
    from flask import Response, stream_with_context, request, session
    from sqlalchemy.sql import text as sa_text

    plan = PlanCadre.query.get(plan_id)
    if not plan:
        def error_stream():
            yield "event: error\ndata: Plan Cadre introuvable\n\n"
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')

    # Grab data from query params (not from request.form)
    field_name = request.args.get('field_name', '')
    prompt_text = request.args.get('prompt_text', '')
    model_name = request.args.get('ai_model', 'gpt-4')
    additional_info = request.args.get('additional_info', '')
    cours_nom = plan.cours.nom if plan.cours else ""
    cours_session = plan.cours.session if plan.cours else ""
    existing_content = request.args.get('existing_content', '')

    # -- Security / business logic checks --
    if not field_name:
        def error_stream2():
            yield "event: error\ndata: Champ (field_name) manquant.\n\n"
        return Response(stream_with_context(error_stream2()), mimetype='text/event-stream')

    # Suppose you store user’s OpenAI key and credits in current_user
    openai_key = current_user.openai_key
    user_credits = current_user.credits or 0.0
    user_id = current_user.id

    # If the user doesn't have an API key or has insufficient credits, respond
    if not openai_key:
        def error_stream3():
            yield "event: error\ndata: Vous n'avez pas de clé OpenAI configurée.\n\n"
        return Response(stream_with_context(error_stream3()), mimetype='text/event-stream')

    # Initialize your custom OpenAI client
    client = OpenAI(api_key=openai_key)

    # We'll build the combined “instruction” for the model
    # Example: you can adapt this to your use-case
    old_text = request.args.get('old_text', '')
    combined_instruction = (
        f"Voici le contenu existant du champ '{field_name}':\n\n"
        f"{old_text}\n\n"
        f"Consignes de l'utilisateur: {prompt_text}\n\n"
        f"Améliore, clarifie ou complète ce texte en gardant son sens. Ne donne que le texte améliore"
    )

    try:
        # Start the streaming call to OpenAI
        response = client.responses.create(
            model=model_name,
            input=[
                {
                    "role": "system",
                    "content": f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', "
                               f"session {cours_session}. "
                },
                {
                    "role": "user",
                    "content": combined_instruction
                }
            ],
            text={
                "format": {
                    "type": "text"
                }
            },
            store=True,
            stream=True,  # <--- Stream is important
        )
    except Exception as ex:
        logging.error(f"OpenAI error: {ex}")
        err_msg = str(ex)

        def error_stream4():
            # now we reference `err_msg` instead of `e`
            yield f"event: error\ndata: Erreur API OpenAI: {err_msg}\n\n"

        return Response(stream_with_context(error_stream4()), mimetype='text/event-stream')


    # We define a generator function that yields SSE "data: ..." lines
    def stream_content():
        try:
            for chunk in response:
                # Debug print
                print("DEBUG chunk =>", chunk)
                
                # 1) Partial text from "delta" events
                if chunk.type == 'response.output_text.delta':
                    partial_text = getattr(chunk, 'delta', '')
                    if partial_text:
                        yield f"event: message\ndata: {partial_text}\n\n"

                # 2) Final text from "done" event
                elif chunk.type == 'response.output_text.done':
                    # Then you could yield "done" or let the loop continue
                    yield "event: done\ndata: done\n\n"

                # 3) Possibly handle "response.completed" or other events
                elif chunk.type == 'response.completed':
                    # Typically means we're fully done
                    yield "event: done\ndata: done\n\n"

            # If the loop ends naturally, also yield done
            yield "event: done\ndata: done\n\n"

        except Exception as ex_inner:
            err_msg = str(ex_inner)
            logging.error(f"Error streaming: {err_msg}")
            yield f"event: error\ndata: Erreur: {err_msg}\n\n"

    return Response(stream_with_context(stream_content()), mimetype='text/event-stream')



@plan_cadre_bp.route('/<int:plan_id>/generate_content', methods=['POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def generate_plan_cadre_content(plan_id):
    from app.tasks import generate_plan_cadre_content_task

    plan = PlanCadre.query.get(plan_id)
    if not plan:
        return jsonify(success=False, message='Plan Cadre non trouvé.')

    form = GenerateContentForm()
    if not form.validate_on_submit():
        return jsonify(success=False, message='Erreur de validation du formulaire.')
    
    # Lancer la tâche Celery
    task = generate_plan_cadre_content_task.delay(plan_id, form.data, current_user.id)
    session['task_id'] = task.id  # Vous pouvez toujours mettre à jour la session si besoin

    # Retourner le task id dans la réponse AJAX
    return jsonify(success=True, message='La génération est en cours. Vous serez notifié une fois terminée.', task_id=task.id)





###############################################################################
# Exporter un plan-cadre en DOCX
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/export', methods=['GET'])
@login_required
@ensure_profile_completed
def export_plan_cadre(plan_id):
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé', 'danger')
        return redirect(url_for('main.index'))

    docx_file = generate_docx_with_template(plan_id)
    if not docx_file:
        flash('Erreur lors de la génération du document', 'danger')
        return redirect(url_for('main.index'))

    safe_course_name = plan_cadre.cours.nom.replace(' ', '_') if plan_cadre.cours else "Plan_Cadre"
    filename = f"Plan_Cadre_{plan_cadre.cours.code}_{safe_course_name}.docx" if plan_cadre.cours else f"Plan_Cadre_{plan_cadre.id}.docx"

    return send_file(
        docx_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


###############################################################################
# Édition d'un plan-cadre (exemple)
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_plan_cadre(plan_id):
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    form = PlanCadreForm()
    if request.method == 'GET':
        # Pré-remplir
        form.place_intro.data = plan_cadre.place_intro
        form.objectif_terminal.data = plan_cadre.objectif_terminal
        form.structure_intro.data = plan_cadre.structure_intro
        form.structure_activites_theoriques.data = plan_cadre.structure_activites_theoriques
        form.structure_activites_pratiques.data = plan_cadre.structure_activites_pratiques
        form.structure_activites_prevues.data = plan_cadre.structure_activites_prevues
        form.eval_evaluation_sommative.data = plan_cadre.eval_evaluation_sommative
        form.eval_nature_evaluations_sommatives.data = plan_cadre.eval_nature_evaluations_sommatives
        form.eval_evaluation_de_la_langue.data = plan_cadre.eval_evaluation_de_la_langue
        form.eval_evaluation_sommatives_apprentissages.data = plan_cadre.eval_evaluation_sommatives_apprentissages

        # Récupérer et remplir les FieldList
        # competences_developpees
        form.competences_developpees.entries = []
        for cdev in plan_cadre.competences_developpees:
            subform = form.competences_developpees.append_entry()
            subform.texte.data = cdev.texte
            subform.texte_description.data = cdev.description

        # objets_cibles
        form.objets_cibles.entries = []
        for oc in plan_cadre.objets_cibles:
            subform = form.objets_cibles.append_entry()
            subform.texte.data = oc.texte
            subform.texte_description.data = oc.description

        # cours_relies
        form.cours_relies.entries = []
        for cr in plan_cadre.cours_relies:
            subform = form.cours_relies.append_entry()
            subform.texte.data = cr.texte
            subform.texte_description.data = cr.description

        # cours_prealables
        form.cours_prealables.entries = []
        for cp in plan_cadre.cours_prealables:
            subform = form.cours_prealables.append_entry()
            subform.texte.data = cp.texte
            subform.texte_description.data = cp.description

        # savoir_etre
        form.savoir_etre.entries = []
        for se_ in plan_cadre.savoirs_etre:
            subform = form.savoir_etre.append_entry()
            subform.texte.data = se_.texte

        # competences_certifiees
        form.competences_certifiees.entries = []
        for cc in plan_cadre.competences_certifiees:
            subform = form.competences_certifiees.append_entry()
            subform.texte.data = cc.texte
            subform.texte_description.data = cc.description

        # cours_corequis
        form.cours_corequis.entries = []
        for cc in plan_cadre.cours_corequis:
            subform = form.cours_corequis.append_entry()
            subform.texte.data = cc.texte
            subform.texte_description.data = cc.description

    elif form.validate_on_submit():
        try:
            plan_cadre.place_intro = form.place_intro.data
            plan_cadre.objectif_terminal = form.objectif_terminal.data
            plan_cadre.structure_intro = form.structure_intro.data
            plan_cadre.structure_activites_theoriques = form.structure_activites_theoriques.data
            plan_cadre.structure_activites_pratiques = form.structure_activites_pratiques.data
            plan_cadre.structure_activites_prevues = form.structure_activites_prevues.data
            plan_cadre.eval_evaluation_sommative = form.eval_evaluation_sommative.data
            plan_cadre.eval_nature_evaluations_sommatives = form.eval_nature_evaluations_sommatives.data
            plan_cadre.eval_evaluation_de_la_langue = form.eval_evaluation_de_la_langue.data
            plan_cadre.eval_evaluation_sommatives_apprentissages = form.eval_evaluation_sommatives_apprentissages.data

            # Vider les relations existantes
            plan_cadre.competences_developpees.clear()
            plan_cadre.objets_cibles.clear()
            plan_cadre.cours_relies.clear()
            plan_cadre.cours_prealables.clear()
            plan_cadre.savoirs_etre.clear()
            plan_cadre.competences_certifiees.clear()
            plan_cadre.cours_corequis.clear()

            # competences_developpees
            for cdev_data in form.competences_developpees.data:
                t = cdev_data['texte']
                d = cdev_data['texte_description']
                plan_cadre.competences_developpees.append(
                    PlanCadreCompetencesDeveloppees(texte=t, description=d)
                )

            # objets_cibles
            for oc_data in form.objets_cibles.data:
                t = oc_data['texte']
                d = oc_data['texte_description']
                plan_cadre.objets_cibles.append(
                    PlanCadreObjetsCibles(texte=t, description=d)
                )

            # cours_relies
            for cr_data in form.cours_relies.data:
                t = cr_data['texte']
                d = cr_data['texte_description']
                plan_cadre.cours_relies.append(
                    PlanCadreCoursRelies(texte=t, description=d)
                )

            # cours_prealables
            for cp_data in form.cours_prealables.data:
                t = cp_data['texte']
                d = cp_data['texte_description']
                plan_cadre.cours_prealables.append(
                    PlanCadreCoursPrealables(texte=t, description=d)
                )

            # savoir_etre
            for se_data in form.savoir_etre.data:
                t = se_data['texte']
                if t.strip():
                    plan_cadre.savoirs_etre.append(
                        PlanCadreSavoirEtre(texte=t)
                    )

            # competences_certifiees
            for cc_data in form.competences_certifiees.data:
                t = cc_data['texte']
                d = cc_data['texte_description']
                plan_cadre.competences_certifiees.append(
                    PlanCadreCompetencesCertifiees(texte=t, description=d)
                )

            # cours_corequis
            for cc_data in form.cours_corequis.data:
                t = cc_data['texte']
                d = cc_data['texte_description']
                plan_cadre.cours_corequis.append(
                    PlanCadreCoursCorequis(texte=t, description=d)
                )

            db.session.commit()
            flash("Plan Cadre mis à jour avec succès!", 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_id))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Erreur update plan_cadre {plan_id}: {e}")
            traceback.print_exc()
            flash(f"Erreur lors de la mise à jour du Plan Cadre : {str(e)}", 'danger')

    return render_template('edit_plan_cadre.html', form=form, plan_id=plan_id, plan=plan_cadre)


###############################################################################
# Supprimer un plan-cadre
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/delete', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def delete_plan_cadre(plan_id):
    form = DeleteForm()
    if form.validate_on_submit():
        plan_cadre = PlanCadre.query.get(plan_id)
        if not plan_cadre:
            flash('Plan Cadre non trouvé.', 'danger')
            return redirect(url_for('main.index'))

        cours_id = plan_cadre.cours_id
        try:
            db.session.delete(plan_cadre)
            db.session.commit()
            flash('Plan Cadre supprimé avec succès!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la suppression du Plan Cadre : {e}', 'danger')

        return redirect(url_for('cours.view_cours', cours_id=cours_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        return redirect(url_for('main.index'))


###############################################################################
# Ajouter une Capacité
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/add_capacite', methods=['GET', 'POST'])
@role_required('admin')
@ensure_profile_completed
def add_capacite(plan_id):
    form = CapaciteForm()
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'GET':
        form.capacite.data = ""
        form.description_capacite.data = ""
        form.ponderation_min.data = 0
        form.ponderation_max.data = 0

    if form.validate_on_submit():
        try:
            cap = form.capacite.data.strip()
            desc = form.description_capacite.data.strip()
            pmin = form.ponderation_min.data
            pmax = form.ponderation_max.data

            if pmin > pmax:
                flash('La pondération minimale ne peut pas être supérieure à la pondération maximale.', 'danger')
                return redirect(url_for('plan_cadre.add_capacite', plan_id=plan_id))

            new_cap = PlanCadreCapacites(
                plan_cadre_id=plan_cadre.id,
                capacite=cap,
                description_capacite=desc,
                ponderation_min=pmin,
                ponderation_max=pmax
            )
            db.session.add(new_cap)
            db.session.commit()
            flash('Capacité ajoutée avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_cadre.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de la capacité : {e}', 'danger')

    return render_template(
        'add_capacite.html',
        form=form,
        plan_id=plan_id,
        cours_id=plan_cadre.cours_id
    )


###############################################################################
# Supprimer une Capacité
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/capacite/<int:capacite_id>/delete', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def delete_capacite(plan_id, capacite_id):
    form = DeleteForm(prefix=f"capacite-{capacite_id}")
    if form.validate_on_submit():
        plan_cadre = PlanCadre.query.get(plan_id)
        if not plan_cadre:
            flash('Plan Cadre non trouvé.', 'danger')
            return redirect(url_for('main.index'))

        cours_id = plan_cadre.cours_id

        try:
            cap = PlanCadreCapacites.query.filter_by(id=capacite_id, plan_cadre_id=plan_id).first()
            if cap:
                db.session.delete(cap)
                db.session.commit()
                flash('Capacité supprimée avec succès!', 'success')
            else:
                flash('Capacité introuvable.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la suppression de la capacité : {e}', 'danger')

        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        plan_cadre = PlanCadre.query.get(plan_id)
        if plan_cadre:
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_id))
        return redirect(url_for('main.index'))
