import json

import pytest
from sqlalchemy.sql.sqltypes import String, Text
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
            f'{field_prefix}-collection_template': '',
            f'{field_prefix}-existing_config': '',
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


def test_plan_cadre_schema_field_template_flow(app, client):
    admin_id, _, _ = _create_plan(app)
    _login(client, admin_id)

    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        section = next(sec for sec in schema.sections if sec.key == 'collections_plan_cadre')
        section_id = section.id
        manager = PlanCadreSchemaManager()
        template_initial = manager.get_collection_template('text_description_list')
        template_updated = manager.get_collection_template('text_list')

    field_prefix = f'new_field_{section_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'create_field',
            'section_id': str(section_id),
            f'{field_prefix}-key': 'nested_info',
            f'{field_prefix}-label': 'Informations imbriquées',
            f'{field_prefix}-field_type': 'textarea',
            f'{field_prefix}-storage': 'extra',
            f'{field_prefix}-storage_column': '',
            f'{field_prefix}-position': '0',
            f'{field_prefix}-active': 'y',
            f'{field_prefix}-collection_template': 'text_description_list',
            f'{field_prefix}-existing_config': '',
            f'{field_prefix}-help_text': '',
            f'{field_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        field = DataSchemaField.query.filter_by(key='nested_info').first()
        assert field is not None
        assert field.config == template_initial
        field_id = field.id

    update_prefix = f'field_{field_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'update_field',
            'field_id': str(field_id),
            f'{update_prefix}-field_id': str(field_id),
            f'{update_prefix}-section_id': str(section_id),
            f'{update_prefix}-key': 'nested_info',
            f'{update_prefix}-label': 'Informations imbriquées',
            f'{update_prefix}-field_type': 'text',
            f'{update_prefix}-storage': 'extra',
            f'{update_prefix}-storage_column': '',
            f'{update_prefix}-position': '1',
            f'{update_prefix}-placeholder': '',
            f'{update_prefix}-active': 'y',
            f'{update_prefix}-collection_template': 'text_list',
            f'{update_prefix}-existing_config': json.dumps(template_initial),
            f'{update_prefix}-help_text': '',
            f'{update_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        updated_field = DataSchemaField.query.get(field_id)
        assert updated_field is not None
        assert updated_field.config == template_updated
        assert updated_field.field_type == 'text'
        assert updated_field.position == 1
        assert updated_field.help_text is not None


def test_plan_cadre_schema_field_custom_config_preserved(app, client):
    admin_id, _, _ = _create_plan(app)
    _login(client, admin_id)

    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        section = next(sec for sec in schema.sections if sec.key == 'collections_plan_cadre')
        section_id = section.id

    field_prefix = f'new_field_{section_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'create_field',
            'section_id': str(section_id),
            f'{field_prefix}-key': 'custom_info',
            f'{field_prefix}-label': 'Personnalisé',
            f'{field_prefix}-field_type': 'textarea',
            f'{field_prefix}-storage': 'extra',
            f'{field_prefix}-storage_column': '',
            f'{field_prefix}-position': '0',
            f'{field_prefix}-active': 'y',
            f'{field_prefix}-collection_template': 'text_list',
            f'{field_prefix}-existing_config': '',
            f'{field_prefix}-help_text': '',
            f'{field_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        field = DataSchemaField.query.filter_by(key='custom_info').first()
        assert field is not None
        field.config = {'type': 'array', 'items': {'type': 'integer'}}
        db.session.commit()
        stored_config = field.config
        field_id = field.id

    update_prefix = f'field_{field_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'update_field',
            'field_id': str(field_id),
            f'{update_prefix}-field_id': str(field_id),
            f'{update_prefix}-section_id': str(section_id),
            f'{update_prefix}-key': 'custom_info',
            f'{update_prefix}-label': 'Personnalisé (modifié)',
            f'{update_prefix}-field_type': 'textarea',
            f'{update_prefix}-storage': 'extra',
            f'{update_prefix}-storage_column': '',
            f'{update_prefix}-position': '2',
            f'{update_prefix}-placeholder': '',
            f'{update_prefix}-active': 'y',
            f'{update_prefix}-collection_template': 'custom',
            f'{update_prefix}-existing_config': json.dumps(stored_config),
            f'{update_prefix}-help_text': '',
            f'{update_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        reloaded = DataSchemaField.query.get(field_id)
        assert reloaded is not None
        assert reloaded.config == stored_config
        assert reloaded.label == 'Personnalisé (modifié)'


def test_plan_cadre_schema_template_requires_extra_storage(app, client):
    admin_id, _, _ = _create_plan(app)
    _login(client, admin_id)

    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        section = next(sec for sec in schema.sections if sec.key == 'repere_generaux')
        section_id = section.id

    field_prefix = f'new_field_{section_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'create_field',
            'section_id': str(section_id),
            f'{field_prefix}-key': 'invalid_collection',
            f'{field_prefix}-label': 'Collection invalide',
            f'{field_prefix}-field_type': 'textarea',
            f'{field_prefix}-storage': 'column',
            f'{field_prefix}-storage_column': 'place_intro',
            f'{field_prefix}-position': '0',
            f'{field_prefix}-active': 'y',
            f'{field_prefix}-collection_template': 'text_list',
            f'{field_prefix}-existing_config': '',
            f'{field_prefix}-help_text': '',
            f'{field_prefix}-submit': 'Enregistrer le champ',
        },
    )

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'Les collections personnalisées doivent utiliser le stockage' in page

    with app.app_context():
        field = DataSchemaField.query.filter_by(key='invalid_collection').first()
        assert field is None


def test_plan_cadre_custom_section_renders_in_view(app, client):
    admin_id, cours_id, plan_id = _create_plan(app)
    _login(client, admin_id)

    with app.app_context():
        manager = PlanCadreSchemaManager()
        schema = manager.ensure_schema()
        custom_section = manager.create_section(schema, {
            'key': 'custom_section',
            'label': 'Section personnalisée',
            'description': 'Section ajoutée dynamiquement.',
            'position': 75,
            'active': True,
        })
        manager.create_field(schema, custom_section, {
            'key': 'custom_field',
            'label': 'Champ personnalisé',
            'field_type': 'textarea',
            'storage': 'extra',
            'position': 10,
            'active': True,
        })
        db.session.commit()

    response = client.get(f'/cours/{cours_id}/plan_cadre/{plan_id}')
    page = response.get_data(as_text=True)
    assert 'Section personnalisée' in page
    assert 'Champ personnalisé' in page


def test_plan_cadre_schema_column_choices_cover_plan_fields(app):
    with app.app_context():
        manager = PlanCadreSchemaManager()
        choices = dict(manager.column_choices())

        expected_columns = {
            column.name
            for column in PlanCadre.__table__.columns
            if isinstance(column.type, (Text, String))
            and column.name not in {'id', 'cours_id', 'modified_by_id', 'modified_at'}
        }

        assert expected_columns.issubset(set(choices.keys()))
        assert choices.get('additional_info') == 'Informations additionnelles'
        assert choices.get('ai_model') == 'Modèle IA'


def test_plan_cadre_default_schema_includes_nested_collections(app):
    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        fields_by_key = {
            field.key: field
            for section in schema.sections
            for field in section.fields
        }

        expected_nested = {
            'capacites',
            'competences_developpees',
            'competences_certifiees',
            'objets_cibles',
            'cours_corequis',
            'cours_prealables',
            'cours_relies',
            'savoirs_etre',
        }

        assert expected_nested.issubset(fields_by_key.keys())
        assert fields_by_key['capacites'].config.get('type') == 'array'
        capacite_props = fields_by_key['capacites'].config['items']['properties']
        assert 'savoirs_necessaires' in capacite_props
        assert capacite_props['savoirs_necessaires']['type'] == 'array'


def test_plan_cadre_schema_create_field_from_template(app, client):
    admin_id, _, _ = _create_plan(app)
    _login(client, admin_id)

    with app.app_context():
        schema = PlanCadreSchemaManager().ensure_schema()
        section = next(sec for sec in schema.sections if sec.key == 'collections_plan_cadre')
        section_id = section.id

    field_prefix = f'new_field_{section_id}'
    response = client.post(
        '/settings/schemas/plan_cadre',
        data={
            'form_name': 'create_field',
            'section_id': str(section_id),
            f'{field_prefix}-key': 'new_collection',
            f'{field_prefix}-label': 'Nouvelle collection',
            f'{field_prefix}-field_type': 'textarea',
            f'{field_prefix}-storage': 'extra',
            f'{field_prefix}-storage_column': '',
            f'{field_prefix}-position': '0',
            f'{field_prefix}-active': 'y',
            f'{field_prefix}-collection_template': 'text_list',
            f'{field_prefix}-existing_config': '',
            f'{field_prefix}-help_text': '',
            f'{field_prefix}-submit': 'Enregistrer le champ',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        manager = PlanCadreSchemaManager()
        template_config = manager.get_collection_template('text_list')
        default_help = manager.get_collection_help_text('text_list')

        field = DataSchemaField.query.filter_by(key='new_collection').first()
        assert field is not None
        assert field.storage == 'extra'
        assert field.config == template_config
        assert field.help_text == default_help
