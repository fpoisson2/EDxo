# plan_de_cours.py
import logging
import traceback

from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, jsonify, session
from flask_login import login_required, current_user

from ..forms import (
    DeleteForm,
    PlanCadreForm,
    GenerateContentForm
)
# Import SQLAlchemy DB and models
from ..models import (
    db,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation
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

@plan_cadre_bp.route('/<int:plan_id>/generate_content', methods=['POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def generate_plan_cadre_content(plan_id):
    from ..tasks.generation_plan_cadre import generate_plan_cadre_content_task

    plan = PlanCadre.query.get(plan_id)
    if not plan:
        return jsonify(success=False, message='Plan Cadre non trouvé.')

    form = GenerateContentForm()
    mode = request.form.get('mode')
    # Validation: en mode 'wand', le champ distinct est utilisé, on évite d'exiger additional_info
    if mode != 'wand':
        if not form.validate_on_submit():
            return jsonify(success=False, message='Erreur de validation du formulaire.')
    
    # Forcer le mode amélioration si demandé explicitement
    # mode déjà défini ci-dessus
    improved_mode = (mode in ('improve', 'wand')) or bool(form.improve_only.data)
    payload = dict(form.data)
    payload['improve_only'] = bool(improved_mode)
    payload['mode'] = mode
    # Instruction spécifique à la baguette magique (facultative)
    wand_instruction = request.form.get('wand_instruction')
    if wand_instruction is not None:
        payload['wand_instruction'] = wand_instruction
    # Propager un périmètre ciblé si présent
    target_cols = request.form.getlist('target_columns') or []
    if not target_cols:
        raw = request.form.get('target_columns')
        if raw:
            target_cols = [s.strip() for s in raw.split(',') if s.strip()]
    if target_cols:
        payload['target_columns'] = target_cols

    # Lancer la tâche Celery
    task = generate_plan_cadre_content_task.delay(plan_id, payload, current_user.id)
    session['task_id'] = task.id  # Vous pouvez toujours mettre à jour la session si besoin

    # Retourner le task id dans la réponse AJAX
    return jsonify(success=True, message='La génération est en cours. Vous serez notifié une fois terminée.', task_id=task.id)


###############################################################################
# Revoir une proposition d'amélioration (aperçu)
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/review', methods=['GET'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def review_improvement(plan_id):
    from celery_app import celery
    from celery.result import AsyncResult

    task_id = request.args.get('task_id')
    if not task_id:
        flash("Identifiant de tâche manquant.", 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=PlanCadre.query.get(plan_id).cours_id, plan_id=plan_id))

    res = AsyncResult(task_id, app=celery)
    if res.state != 'SUCCESS' or not res.result or not res.result.get('preview'):
        flash("Aucune proposition d'amélioration trouvée pour cette tâche.", 'warning')
        return redirect(url_for('cours.view_plan_cadre', cours_id=PlanCadre.query.get(plan_id).cours_id, plan_id=plan_id))

    proposed = res.result.get('proposed', {})
    plan = PlanCadre.query.get(plan_id)
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Calcul des changements simples: on ne montre que ce qui change
    changes = {}
    # Champs texte simples
    simple_fields = [
        'place_intro', 'objectif_terminal', 'structure_intro',
        'structure_activites_theoriques', 'structure_activites_pratiques',
        'structure_activites_prevues', 'eval_evaluation_sommative',
        'eval_nature_evaluations_sommatives', 'eval_evaluation_de_la_langue',
        'eval_evaluation_sommatives_apprentissages'
    ]
    for key in simple_fields:
        new_val = (proposed.get('fields') or {}).get(key)
        if new_val is not None and (getattr(plan, key) or '').strip() != (new_val or '').strip():
            changes[key] = {
                'before': getattr(plan, key) or '',
                'after': new_val or ''
            }

    # Listes avec description
    list_mappings = {
        'Description des compétences développées': 'competences_developpees',
        'Description des Compétences certifiées': 'competences_certifiees',
        'Description des cours corequis': 'cours_corequis',
        'Description des cours préalables': 'cours_prealables',
        'Objets cibles': 'objets_cibles'
    }
    for display_name, rel_attr in list_mappings.items():
        new_list = (proposed.get('fields_with_description') or {}).get(display_name)
        if new_list is None:
            continue
        before_list = [
            {'texte': getattr(item, 'texte', ''), 'description': getattr(item, 'description', '')}
            for item in getattr(plan, rel_attr)
        ]
        if before_list != new_list:
            changes[rel_attr] = {
                'before': before_list,
                'after': new_list,
                'label': display_name
            }

    # Savoir-être
    if proposed.get('savoir_etre') is not None:
        before_se = [{'texte': se.texte} for se in plan.savoirs_etre]
        after_se = [{'texte': se} for se in (proposed.get('savoir_etre') or [])]
        if before_se != after_se:
            changes['savoirs_etre'] = {
                'before': before_se,
                'after': after_se,
                'label': 'Savoir-être'
            }

    # Capacités (comparaison simple sur contenu brut)
    if proposed.get('capacites') is not None:
        before_caps = []
        for cap in plan.capacites:
            before_caps.append({
                'capacite': cap.capacite,
                'description_capacite': cap.description_capacite,
                'ponderation_min': cap.ponderation_min,
                'ponderation_max': cap.ponderation_max,
                'savoirs_necessaires': [sn.texte for sn in cap.savoirs_necessaires],
                'savoirs_faire': [
                    {
                        'texte': sf.texte,
                        'cible': sf.cible,
                        'seuil_reussite': sf.seuil_reussite
                    } for sf in cap.savoirs_faire
                ],
                'moyens_evaluation': [me.texte for me in cap.moyens_evaluation]
            })
        if before_caps != proposed.get('capacites'):
            changes['capacites'] = {
                'before': before_caps,
                'after': proposed.get('capacites'),
                'label': 'Capacités'
            }

    return render_template(
        'review_plan_cadre_improvement.html',
        plan=plan,
        cours=plan.cours,
        plan_id=plan_id,
        task_id=task_id,
        changes=changes
    )


###############################################################################
# Appliquer une proposition d'amélioration
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/apply_improvement', methods=['POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def apply_improvement(plan_id):
    from celery_app import celery
    from celery.result import AsyncResult
    plan = PlanCadre.query.get(plan_id)
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    task_id = request.form.get('task_id')
    if not task_id:
        flash("Identifiant de tâche manquant.", 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    res = AsyncResult(task_id, app=celery)
    if res.state != 'SUCCESS' or not res.result or not res.result.get('preview'):
        flash("Impossible de récupérer la proposition d'amélioration.", 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    proposed = res.result.get('proposed', {})

    try:
        # Appliquer champs simples selon sélection
        accept_fields = request.form.getlist('accept_fields_keys')
        fields = proposed.get('fields') or {}
        for key in fields.keys():
            if key in accept_fields:
                setattr(plan, key, fields.get(key))

        # Réinitialiser et appliquer listes avec description
        def reset_and_apply(current_list, model_cls, items):
            # Vider la liste actuelle
            current_list.clear()
            for it in items:
                obj = model_cls(texte=it.get('texte') or '', description=it.get('description') or '')
                current_list.append(obj)

        mapping_attr_to_model = {
            'competences_developpees': PlanCadreCompetencesDeveloppees,
            'competences_certifiees': PlanCadreCompetencesCertifiees,
            'cours_corequis': PlanCadreCoursCorequis,
            'cours_prealables': PlanCadreCoursPrealables,
            'objets_cibles': PlanCadreObjetsCibles
        }
        reverse_map = {
            'Description des compétences développées': 'competences_developpees',
            'Description des Compétences certifiées': 'competences_certifiees',
            'Description des cours corequis': 'cours_corequis',
            'Description des cours préalables': 'cours_prealables',
            'Objets cibles': 'objets_cibles'
        }
        # Actions possibles: keep | replace | merge (pour listes simples)
        actions = request.form.to_dict(flat=False)
        for display_key, items in (proposed.get('fields_with_description') or {}).items():
            attr = reverse_map.get(display_key)
            if not attr:
                continue
            model_cls = mapping_attr_to_model.get(attr)
            if not model_cls:
                continue
            action_key = f'action[{attr}]'
            action_val = request.form.get(action_key, 'keep')
            current_rel = getattr(plan, attr)
            if action_val == 'replace':
                reset_and_apply(current_rel, model_cls, items)
            elif action_val == 'merge':
                selected_indices = request.form.getlist(f'accept_items[{attr}]')
                # Ajouter uniquement les éléments sélectionnés
                for idx_str in selected_indices:
                    try:
                        idx = int(idx_str)
                    except ValueError:
                        continue
                    if 0 <= idx < len(items):
                        it = items[idx]
                        current_rel.append(model_cls(texte=it.get('texte') or '', description=it.get('description') or ''))
            # keep => ne rien faire

        # Savoir-être
        if proposed.get('savoir_etre') is not None:
            se_action = request.form.get('action[savoirs_etre]', 'keep')
            if se_action == 'replace':
                plan.savoirs_etre.clear()
                for se_txt in (proposed.get('savoir_etre') or []):
                    if (se_txt or '').strip():
                        plan.savoirs_etre.append(PlanCadreSavoirEtre(texte=se_txt.strip()))
            elif se_action == 'merge':
                selected_indices = request.form.getlist('accept_items[savoirs_etre]')
                items = proposed.get('savoir_etre') or []
                for idx_str in selected_indices:
                    try:
                        idx = int(idx_str)
                    except ValueError:
                        continue
                    if 0 <= idx < len(items):
                        se_txt = (items[idx] or '').strip()
                        if se_txt:
                            plan.savoirs_etre.append(PlanCadreSavoirEtre(texte=se_txt))
            # keep => rien

        # Capacités
        if proposed.get('capacites') is not None:
            cap_action = request.form.get('action[capacites]', 'keep')
            if cap_action == 'replace':
                plan.capacites.clear()
                for cap in (proposed.get('capacites') or []):
                    new_cap = PlanCadreCapacites(
                        capacite=cap.get('capacite') or '',
                        description_capacite=cap.get('description_capacite') or '',
                        ponderation_min=int(cap.get('ponderation_min') or 0),
                        ponderation_max=int(cap.get('ponderation_max') or 0)
                    )
                    plan.capacites.append(new_cap)
                    for sn in (cap.get('savoirs_necessaires') or []):
                        new_cap.savoirs_necessaires.append(
                            PlanCadreCapaciteSavoirsNecessaires(texte=sn or '')
                        )
                    for sf in (cap.get('savoirs_faire') or []):
                        new_cap.savoirs_faire.append(
                            PlanCadreCapaciteSavoirsFaire(
                                texte=sf.get('texte') or '',
                                cible=sf.get('cible') or '',
                                seuil_reussite=sf.get('seuil_reussite') or ''
                            )
                        )
                    for me in (cap.get('moyens_evaluation') or []):
                        new_cap.moyens_evaluation.append(
                            PlanCadreCapaciteMoyensEvaluation(texte=me or '')
                        )
            elif cap_action == 'merge':
                # Ajout partiel: capacités sélectionnées et sous-éléments cochés
                selected_caps = request.form.getlist('accept_items[capacites]')
                items = proposed.get('capacites') or []
                for cap_idx_str in selected_caps:
                    try:
                        cap_idx = int(cap_idx_str)
                    except ValueError:
                        continue
                    if not (0 <= cap_idx < len(items)):
                        continue
                    cap = items[cap_idx]
                    new_cap = PlanCadreCapacites(
                        capacite=cap.get('capacite') or '',
                        description_capacite=cap.get('description_capacite') or '',
                        ponderation_min=int(cap.get('ponderation_min') or 0),
                        ponderation_max=int(cap.get('ponderation_max') or 0)
                    )
                    plan.capacites.append(new_cap)
                    # sous-sélection
                    # savoirs_necessaires
                    sel_sn = request.form.getlist(f'accept_items[capacites][{cap_idx}][savoirs_necessaires]')
                    if sel_sn:
                        for idx_str in sel_sn:
                            try:
                                si = int(idx_str)
                            except ValueError:
                                continue
                            if 0 <= si < len(cap.get('savoirs_necessaires') or []):
                                new_cap.savoirs_necessaires.append(
                                    PlanCadreCapaciteSavoirsNecessaires(
                                        texte=(cap['savoirs_necessaires'][si] or '')
                                    )
                                )
                    else:
                        for sn in (cap.get('savoirs_necessaires') or []):
                            new_cap.savoirs_necessaires.append(
                                PlanCadreCapaciteSavoirsNecessaires(texte=sn or '')
                            )
                    # savoirs_faire
                    sel_sf = request.form.getlist(f'accept_items[capacites][{cap_idx}][savoirs_faire]')
                    if sel_sf:
                        for idx_str in sel_sf:
                            try:
                                si = int(idx_str)
                            except ValueError:
                                continue
                            sflist = cap.get('savoirs_faire') or []
                            if 0 <= si < len(sflist):
                                sf = sflist[si]
                                new_cap.savoirs_faire.append(
                                    PlanCadreCapaciteSavoirsFaire(
                                        texte=sf.get('texte') or '',
                                        cible=sf.get('cible') or '',
                                        seuil_reussite=sf.get('seuil_reussite') or ''
                                    )
                                )
                    else:
                        for sf in (cap.get('savoirs_faire') or []):
                            new_cap.savoirs_faire.append(
                                PlanCadreCapaciteSavoirsFaire(
                                    texte=sf.get('texte') or '',
                                    cible=sf.get('cible') or '',
                                    seuil_reussite=sf.get('seuil_reussite') or ''
                                )
                            )
                    # moyens_evaluation
                    sel_me = request.form.getlist(f'accept_items[capacites][{cap_idx}][moyens_evaluation]')
                    if sel_me:
                        for idx_str in sel_me:
                            try:
                                si = int(idx_str)
                            except ValueError:
                                continue
                            if 0 <= si < len(cap.get('moyens_evaluation') or []):
                                new_cap.moyens_evaluation.append(
                                    PlanCadreCapaciteMoyensEvaluation(
                                        texte=(cap['moyens_evaluation'][si] or '')
                                    )
                                )
                    else:
                        for me in (cap.get('moyens_evaluation') or []):
                            new_cap.moyens_evaluation.append(
                                PlanCadreCapaciteMoyensEvaluation(texte=me or '')
                            )

        db.session.commit()
        flash("Améliorations appliquées avec succès.", 'success')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Erreur lors de l'application de l'amélioration: {e}")
        flash(f"Erreur lors de l'application des changements: {e}", 'danger')

    return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))





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
