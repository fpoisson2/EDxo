"""API endpoints for core operations."""

from functools import wraps
from datetime import timedelta
from src.utils.datetime_utils import now_utc, ensure_aware_utc
import secrets

from flask import Blueprint, jsonify, send_file, request, g
from flask_login import current_user, login_required

from .oauth import _json_error

from ..models import (
    Programme,
    Cours,
    Competence,
    PlanCadre,
    PlanDeCours,
    User,
    OAuthToken,
    db,
)

api_bp = Blueprint('api', __name__, url_prefix='/api')


def api_auth_required(f):
    """Allow access with logged in user or valid X-API-Token header."""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-API-Token')
        if token is not None:
            user = User.query.filter_by(api_token=token).first()
            if user and user.api_token_expires_at and ensure_aware_utc(user.api_token_expires_at) > now_utc():
                g.api_user = user
                return f(*args, **kwargs)
            return _json_error(401, 'invalid_token', 'Authentication required')
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            bearer = auth_header.split(' ', 1)[1]
            oauth = OAuthToken.query.filter_by(token=bearer).first()
            if oauth and oauth.is_valid():
                g.api_client = oauth.client_id
                if oauth.user:
                    g.api_user = oauth.user
                return f(*args, **kwargs)
            return _json_error(401, 'invalid_token', 'Authentication required')
        if current_user.is_authenticated:
            g.api_user = current_user
            return f(*args, **kwargs)
        return _json_error(401, 'invalid_token', 'Authentication required')

    return decorated


@api_bp.route('/token', methods=['GET', 'POST'])
@login_required
def api_token():
    """Return or generate an API token for the current user."""
    user = current_user
    if request.method == 'POST':
        ttl = request.args.get('ttl', type=int)
        expires_in = ttl if ttl is not None else 30 * 24 * 3600
        user.generate_api_token(expires_in=expires_in)
        status = 201
    elif not user.api_token or not user.api_token_expires_at or ensure_aware_utc(user.api_token_expires_at) <= now_utc():
        user.generate_api_token(expires_in=30 * 24 * 3600)
        status = 201
    else:
        status = 200
    return (
        jsonify(
            {
                'token': user.api_token,
                'expires_at': user.api_token_expires_at.isoformat(),
            }
        ),
        status,
    )


@api_bp.get('/programmes')
@api_auth_required
def list_programmes():
    programmes = Programme.query.all()
    data = [{'id': p.id, 'nom': p.nom} for p in programmes]
    return jsonify(data)


@api_bp.get('/programmes/<int:programme_id>/cours')
@api_auth_required
def list_courses_for_program(programme_id):
    programme = Programme.query.get_or_404(programme_id)
    courses = [{'id': c.id, 'code': c.code, 'nom': c.nom} for c in programme.cours]
    return jsonify(courses)


@api_bp.get('/programmes/<int:programme_id>/competences')
@api_auth_required
def list_competences_for_program(programme_id):
    competences = Competence.query.filter_by(programme_id=programme_id).order_by(Competence.code).all()
    data = [{'id': c.id, 'code': c.code, 'nom': c.nom} for c in competences]
    return jsonify(data)


@api_bp.get('/competences/<int:competence_id>')
@api_auth_required
def competence_details(competence_id):
    comp = Competence.query.get_or_404(competence_id)
    elements = [
        {
            'id': e.id,
            'nom': e.nom,
            'criteres': [c.criteria for c in e.criteria]
        }
        for e in comp.elements
    ]
    return jsonify({
        'id': comp.id,
        'programme_id': comp.programme_id,
        'code': comp.code,
        'nom': comp.nom,
        'criteria_de_performance': comp.criteria_de_performance,
        'contexte_de_realisation': comp.contexte_de_realisation,
        'elements': elements
    })


@api_bp.get('/cours')
@api_auth_required
def list_courses():
    courses = Cours.query.all()
    data = [{'id': c.id, 'code': c.code, 'nom': c.nom} for c in courses]
    return jsonify(data)


@api_bp.get('/cours/<int:cours_id>')
@api_auth_required
def course_details(cours_id):
    cours = Cours.query.get_or_404(cours_id)
    return jsonify({'id': cours.id, 'code': cours.code, 'nom': cours.nom})


@api_bp.get('/cours/<int:cours_id>/plan_cadre')
@api_auth_required
def plan_cadre_details(cours_id):
    plan = PlanCadre.query.filter_by(cours_id=cours_id).first()
    if not plan:
        return jsonify({}), 404
    return jsonify(plan.to_dict())


@api_bp.get('/cours/<int:cours_id>/plans_de_cours')
@api_auth_required
def plans_de_cours_list(cours_id):
    plans = PlanDeCours.query.filter_by(cours_id=cours_id).all()
    return jsonify([p.to_dict() for p in plans])


@api_bp.post('/plan_cadre/<int:plan_id>/generate')
@api_auth_required
def generate_plan_cadre(plan_id):
    from ..tasks.generation_plan_cadre import generate_plan_cadre_content_task
    task = generate_plan_cadre_content_task.delay(plan_id, {}, g.api_user.id)
    return jsonify({'task_id': task.id}), 202


@api_bp.post('/plan_de_cours/<int:plan_id>/generate')
@api_auth_required
def generate_plan_de_cours(plan_id):
    from ..tasks.generation_plan_de_cours import generate_plan_de_cours_all_task
    task = generate_plan_de_cours_all_task.delay(plan_id, '', 'gpt-4o', g.api_user.id)
    return jsonify({'task_id': task.id}), 202


@api_bp.post('/plan_cadre/<int:plan_id>/improve')
@api_auth_required
def improve_plan_cadre(plan_id):
    from ..tasks.generation_plan_cadre import generate_plan_cadre_content_task
    payload = {'improve_only': True}
    task = generate_plan_cadre_content_task.delay(plan_id, payload, g.api_user.id)
    return jsonify({'task_id': task.id}), 202


@api_bp.post('/plan_cadre/<int:plan_id>/improve/<string:section>')
@api_auth_required
def improve_plan_cadre_section(plan_id, section):
    from ..tasks.generation_plan_cadre import generate_plan_cadre_content_task
    payload = {'improve_only': True, 'target_columns': [section]}
    task = generate_plan_cadre_content_task.delay(plan_id, payload, g.api_user.id)
    return jsonify({'task_id': task.id}), 202


@api_bp.get('/plan_cadre/<int:plan_id>/section/<string:section>')
@api_auth_required
def get_plan_cadre_section(plan_id, section):
    plan = PlanCadre.query.get_or_404(plan_id)
    if not hasattr(plan, section):
        return jsonify({'error': 'Section inconnue'}), 404
    return jsonify({section: getattr(plan, section)})


@api_bp.get('/plan_cadre/<int:plan_id>/export_docx')
@api_auth_required
def export_plan_cadre_docx(plan_id):
    from ...utils import generate_docx_with_template
    plan = PlanCadre.query.get_or_404(plan_id)
    docx_file = generate_docx_with_template(plan_id)
    if not docx_file:
        return jsonify({'error': 'generation failed'}), 400
    safe_course_name = plan.cours.nom.replace(' ', '_') if plan.cours else 'Plan_Cadre'
    filename = f"Plan_Cadre_{plan.cours.code}_{safe_course_name}.docx" if plan.cours else f"Plan_Cadre_{plan.id}.docx"
    return send_file(
        docx_file,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


@api_bp.get('/plan_de_cours/<int:plan_id>/export_docx')
@api_auth_required
def export_plan_de_cours_docx(plan_id):
    from .plan_de_cours import export_docx as export_pdc
    plan = PlanDeCours.query.get_or_404(plan_id)
    return export_pdc(plan.cours_id, plan.session)
