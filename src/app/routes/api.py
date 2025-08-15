from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..models import (
    db,
    Programme,
    Cours,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    PlanDeCours,
    PlanDeCoursPromptSettings,
    User,
)
from ...extensions import csrf
from ..routes.plan_de_cours import build_all_prompt
from ...celery_app import celery
from celery.result import AsyncResult
from ..tasks.generation_plan_cadre import generate_plan_cadre_content_task
from ..tasks.generation_plan_de_cours import generate_plan_de_cours_all_task


api_bp = Blueprint("api", __name__, url_prefix="/api")


def _cours_to_dict(c: Cours) -> Dict[str, Any]:
    return {"id": c.id, "code": c.code, "nom": c.nom}


# ---------- Programmes ----------
@api_bp.get("/programmes")
@login_required
def api_list_programmes():
    rows = Programme.query.order_by(Programme.id).all()
    return jsonify([{"id": r.id, "nom": r.nom} for r in rows])


# ---------- Cours ----------
@api_bp.get("/cours")
@login_required
def api_list_cours():
    programme_id = request.args.get("programme_id", type=int)
    q = Cours.query
    if programme_id:
        # Uses legacy-compatible hybrid property
        q = q.filter_by(programme_id=programme_id)
    rows = q.order_by(Cours.id).all()
    return jsonify([_cours_to_dict(r) for r in rows])


@api_bp.get("/cours/by_code")
@login_required
def api_find_cours_by_code():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"error": "code requis"}), 400
    row = Cours.query.filter(Cours.code.ilike(code)).first()
    if not row:
        like = f"%{code}%"
        row = Cours.query.filter(Cours.code.ilike(like)).order_by(Cours.id.asc()).first()
    if not row:
        return jsonify(None)
    return jsonify({"id": row.id, "code": row.code, "nom": row.nom, "programme_id": row.programme_id})


@api_bp.get("/cours/<int:cours_id>")
@login_required
def api_get_cours(cours_id: int):
    c = Cours.query.get(cours_id)
    if not c:
        return jsonify({"error": "Cours non trouvé"}), 404
    return jsonify(_cours_to_dict(c))


@api_bp.get("/cours/<int:cours_id>/plan_cadre")
@login_required
def api_get_plan_cadre_id_for_cours(cours_id: int):
    pc = PlanCadre.query.filter_by(cours_id=cours_id).first()
    return jsonify({"plan_cadre_id": int(pc.id) if pc else None})


# ---------- PlanCadre ----------
@api_bp.get("/plan_cadre/<int:plan_id>/capacites")
@login_required
def api_get_plan_cadre_capacites(plan_id: int):
    pc = PlanCadre.query.get(plan_id)
    if not pc:
        return jsonify([])
    out: List[Dict[str, Any]] = []
    for cap in pc.capacites:
        out.append({
            "id": cap.id,
            "capacite": cap.capacite,
            "description_capacite": cap.description_capacite,
            "ponderation_min": cap.ponderation_min,
            "ponderation_max": cap.ponderation_max,
            "savoirs_necessaires": [sn.texte for sn in cap.savoirs_necessaires],
            "savoirs_faire": [
                {
                    "texte": sf.texte,
                    "cible": sf.cible,
                    "seuil_reussite": sf.seuil_reussite,
                } for sf in cap.savoirs_faire
            ],
            "moyens_evaluation": [me.texte for me in cap.moyens_evaluation],
        })
    return jsonify(out)


@api_bp.post("/plan_cadre/<int:plan_id>/capacites")
@csrf.exempt
@login_required
def api_add_plan_cadre_capacite(plan_id: int):
    data = request.get_json() or {}
    capacite = (data.get("capacite") or "").strip()
    description = (data.get("description_capacite") or "").strip()
    pmin = int(data.get("ponderation_min") or 0)
    pmax = int(data.get("ponderation_max") or 0)

    pc = PlanCadre.query.get(plan_id)
    if not pc:
        return jsonify({"success": False, "message": "Plan-cadre non trouvé"}), 404

    new_cap = PlanCadreCapacites(
        capacite=capacite,
        description_capacite=description,
        ponderation_min=pmin,
        ponderation_max=pmax,
    )
    pc.capacites.append(new_cap)
    db.session.commit()
    return jsonify({"success": True, "id": new_cap.id})


@api_bp.post("/plan_cadre/<int:plan_id>/generate")
@csrf.exempt
@login_required
def api_pc_generate(plan_id: int):
    data = request.get_json() or {}
    mode = data.get("mode") or "wand"
    target_columns = data.get("target_columns")
    wand_instruction = data.get("wand_instruction")

    payload: Dict[str, Any] = {
        "improve_only": bool(mode in ("improve", "wand")),
        "mode": mode,
    }
    if target_columns:
        payload["target_columns"] = target_columns
    if wand_instruction:
        payload["wand_instruction"] = wand_instruction

    task = generate_plan_cadre_content_task.delay(plan_id, payload, None)
    return jsonify({"success": True, "task_id": task.id})


@api_bp.post("/plan_cadre/<int:plan_id>/apply_improvement")
@csrf.exempt
@login_required
def api_pc_apply_improvement(plan_id: int):
    """Apply the proposed improvement in 'replace all' mode based on a Celery result.

    Body JSON: {"task_id": str}
    """
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "task_id requis"}), 400

    from ..routes.plan_cadre import (
        PlanCadreCompetencesDeveloppees,
        PlanCadreCompetencesCertifiees,
        PlanCadreCoursCorequis,
        PlanCadreCoursPrealables,
        PlanCadreObjetsCibles,
        PlanCadreSavoirEtre,
    )

    plan = PlanCadre.query.get(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Plan Cadre non trouvé."}), 404

    res = AsyncResult(task_id, app=celery)
    if res.state != 'SUCCESS' or not res.result or not res.result.get('preview'):
        return jsonify({"success": False, "message": "Proposition introuvable pour cette tâche."}), 400

    proposed = res.result.get('proposed', {})

    # Apply simple fields (replace)
    fields = proposed.get('fields') or {}
    for key, val in fields.items():
        setattr(plan, key, val)

    # Replace lists with description
    def reset_and_apply(current_list, model_cls, items):
        current_list.clear()
        for it in items:
            current_list.append(model_cls(texte=it.get('texte') or '', description=it.get('description') or ''))

    reverse_map = {
        'Description des compétences développées': ('competences_developpees', PlanCadreCompetencesDeveloppees),
        'Description des Compétences certifiées': ('competences_certifiees', PlanCadreCompetencesCertifiees),
        'Description des cours corequis': ('cours_corequis', PlanCadreCoursCorequis),
        'Description des cours préalables': ('cours_prealables', PlanCadreCoursPrealables),
        'Objets cibles': ('objets_cibles', PlanCadreObjetsCibles),
    }
    for display_key, items in (proposed.get('fields_with_description') or {}).items():
        mapping = reverse_map.get(display_key)
        if not mapping:
            continue
        attr, model_cls = mapping
        reset_and_apply(getattr(plan, attr), model_cls, items)

    # Replace savoir_etre
    plan.savoirs_etre.clear()
    for se_txt in (proposed.get('savoir_etre') or []):
        if (se_txt or '').strip():
            plan.savoirs_etre.append(PlanCadreSavoirEtre(texte=se_txt.strip()))

    # Replace capacities fully
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

    db.session.commit()
    return jsonify({"success": True})


# ---------- Plan de cours ----------
@api_bp.post("/plan_de_cours/generate_all_start")
@csrf.exempt
@login_required
def api_pdc_generate_all_start():
    data = request.get_json() or {}
    try:
        cours_id = int(data.get('cours_id'))
    except Exception:
        cours_id = None
    session = data.get('session')
    additional_info = data.get('additional_info')
    ai_model_override = data.get('ai_model')

    if not cours_id or not session:
        return jsonify({'success': False, 'message': 'cours_id et session requis.'}), 400

    pdc = PlanDeCours.query.filter_by(cours_id=cours_id, session=session).first()
    if not pdc:
        return jsonify({'success': False, 'message': 'Plan de cours non trouvé.'}), 404

    cours = pdc.cours
    plan_cadre = cours.plan_cadre if cours else None
    if not plan_cadre:
        return jsonify({'success': False, 'message': 'Plan cadre non trouvé pour ce cours.'}), 404

    ps = PlanDeCoursPromptSettings.query.filter_by(field_name='all').first()
    ai_model = (ai_model_override or (ps.ai_model if ps else None)) or 'gpt-4o'
    prompt_tmpl = ps.prompt_template if ps else None
    prompt = build_all_prompt(plan_cadre, cours, session, prompt_tmpl, additional_info=additional_info)

    task = generate_plan_de_cours_all_task.delay(pdc.id, prompt, ai_model, None)
    return jsonify({'success': True, 'task_id': task.id})

