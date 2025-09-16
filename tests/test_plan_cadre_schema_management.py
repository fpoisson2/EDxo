import pytest
from werkzeug.security import generate_password_hash

from src.app.models import (
    DataSchemaField,
    DataSchemaRecord,
    DataSchemaSection,
    Department,
    PlanCadre,
    Programme,
    Cours,
    User,
)
from src.extensions import db
from src.utils.schema_manager import PlanCadreSchemaManager


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _create_plan(app):
    with app.app_context():
        dept = Department(nom='Sciences', cegep_id=None)
        db.session.add(dept)
        db.session.flush()

        programme = Programme(nom='Tech', department_id=dept.id)
        db.session.add(programme)
        db.session.flush()

        cours = Cours(
            code='420-ABC',
            nom='Programmation',
            heures_theorie=0,
            heures_laboratoire=0,
            heures_travail_maison=0,
        )
        db.session.add(cours)
        db.session.flush()
        cours.programmes.append(programme)
        db.session.flush()

        plan = PlanCadre(cours_id=cours.id)
        db.session.add(plan)
        db.session.flush()

        admin = User(
            username='admin',
            password=generate_password_hash('secret'),
            role='admin',
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.commit()

        # Ensure defaults exist for schema
        manager = PlanCadreSchemaManager()
        manager.ensure_schema()

        return admin.id, cours.id, plan.id


def test_plan_cadre_schema_dynamic_field_flow(app, client):
    admin_id, cours_id, plan_id = _create_plan(app)
    _login(client, admin_id)

    # Retrieve section for extra fields creation (use first section)
    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        section = next(sec for sec in schema.sections if sec.key == 'repere_generaux')
        section_id = section.id

    # Add a new extra field through the UI form
    field_prefix = f'new_field_{section_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'create_field',
            'section_id': str(section_id),
            f'{field_prefix}-key': 'info_sup',
            f'{field_prefix}-label': 'Informations supplémentaires',
            f'{field_prefix}-field_type': 'textarea',
            f'{field_prefix}-storage': 'extra',
            f'{field_prefix}-storage_column': '',
            f'{field_prefix}-position': '0',
            f'{field_prefix}-active': 'y',
            f'{field_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        field = DataSchemaField.query.filter_by(key='info_sup').first()
        assert field is not None
        assert field.storage == 'extra'
        assert field.section_id == section_id

    # Verify the field is rendered on the plan-cadre page
    response = client.get(f'/cours/{cours_id}/plan_cadre/{plan_id}')
    assert response.status_code == 200
    assert 'Informations supplémentaires' in response.get_data(as_text=True)

    # Submit an update including the extra field value
    update_payload = {
        'place_intro': 'Texte',
        'objectif_terminal': '',
        'structure_intro': '',
        'structure_activites_theoriques': '',
        'structure_activites_pratiques': '',
        'structure_activites_prevues': '',
        'eval_evaluation_sommative': '',
        'eval_nature_evaluations_sommatives': '',
        'eval_evaluation_de_la_langue': '',
        'eval_evaluation_sommatives_apprentissages': '',
        'extra__info_sup': 'Une note qui persiste',
    }
    response = client.post(
        f'/cours/{cours_id}/plan_cadre/{plan_id}',
        data=update_payload,
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        record = DataSchemaRecord.get_or_create(schema.id, 'PlanCadre', plan_id)
        assert record.data.get('info_sup') == 'Une note qui persiste'

    # Archive the field via the UI
    with app.app_context():
        field_id = DataSchemaField.query.filter_by(key='info_sup').first().id
    toggle_prefix = f'toggle_{field_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'archive_field',
            'field_id': str(field_id),
            f'{toggle_prefix}-field_id': str(field_id),
            f'{toggle_prefix}-submit': 'Archiver',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        archived_field = DataSchemaField.query.get(field_id)
        assert archived_field is not None
        assert not archived_field.is_active
        # Data still preserved for the plan
        schema = PlanCadreSchemaManager().ensure_schema()
        record = DataSchemaRecord.get_or_create(schema.id, 'PlanCadre', plan_id)
        assert record.data.get('info_sup') == 'Une note qui persiste'

    # The archived field no longer appears on the plan editing view
    response = client.get(f'/cours/{cours_id}/plan_cadre/{plan_id}')
    page = response.get_data(as_text=True)
    assert 'Informations supplémentaires' not in page
