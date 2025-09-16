"""Gestion centralisée des schémas dynamiques (plan-cadre & extensions)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from flask import current_app

from src.app.models import (
    DataSchema,
    DataSchemaField,
    DataSchemaRecord,
    DataSchemaSection,
    PlanCadre,
)
from src.extensions import db


@dataclass
class FieldContext:
    key: str
    label: str
    storage: str
    section_key: str
    html_name: str
    html_id: str
    field_type: str
    help_text: Optional[str]
    placeholder: Optional[str]
    required: bool
    storage_column: Optional[str]
    form_field: Optional[object]
    improve_target: Optional[str]
    value: Optional[str]


@dataclass
class SectionContext:
    key: str
    label: str
    description: Optional[str]
    position: int
    fields: List[FieldContext]


class SchemaManager:
    """Gestionnaire générique pour un schéma configuré."""

    slug: str = ''
    owner_type: str = ''

    def ensure_schema(self) -> DataSchema:
        schema = DataSchema.get_by_slug(self.slug)
        if not schema:
            schema = DataSchema(slug=self.slug, name=self.default_name, description=self.default_description)
            db.session.add(schema)
            db.session.flush()
        self._ensure_default_sections(schema)
        return schema

    # ---------------------------
    # Hooks for subclasses
    # ---------------------------

    @property
    def default_name(self) -> str:
        raise NotImplementedError

    @property
    def default_description(self) -> str:
        return None

    def default_sections(self) -> Iterable[Dict]:
        return []

    def column_choices(self) -> List[tuple]:
        return []

    def validate_column(self, column_name: str) -> bool:
        return any(col == column_name for col, _ in self.column_choices())

    # ---------------------------
    # Internal helpers
    # ---------------------------

    def _ensure_default_sections(self, schema: DataSchema) -> None:
        existing_sections = {section.key: section for section in schema.sections}
        for section_def in self.default_sections():
            section = existing_sections.get(section_def['key'])
            if not section:
                section = DataSchemaSection(
                    schema=schema,
                    key=section_def['key'],
                    label=section_def['label'],
                    description=section_def.get('description'),
                    position=section_def.get('position', 0),
                    active=True,
                )
                db.session.add(section)
                db.session.flush()
            else:
                # Keep schema label up to date if admin has not customised it manually
                if section.label == section_def['label'] and section_def.get('label_update'):
                    section.label = section_def['label_update']
            self._ensure_default_fields(schema, section, section_def.get('fields', []))

    def _ensure_default_fields(self, schema: DataSchema, section: DataSchemaSection, fields: Iterable[Dict]) -> None:
        existing_fields = {field.key: field for field in section.fields}
        for field_def in fields:
            field = existing_fields.get(field_def['key'])
            if field:
                continue
            storage = field_def.get('storage', 'extra')
            field = DataSchemaField(
                schema=schema,
                section=section,
                key=field_def['key'],
                label=field_def['label'],
                help_text=field_def.get('help_text'),
                field_type=field_def.get('field_type', 'textarea'),
                storage=storage,
                storage_column=field_def.get('storage_column') if storage == 'column' else None,
                position=field_def.get('position', 0),
                required=field_def.get('required', False),
                active=True,
                placeholder=field_def.get('placeholder'),
                config=field_def.get('config', {}),
            )
            db.session.add(field)

    # ---------------------------
    # CRUD helpers
    # ---------------------------

    def create_section(self, schema: DataSchema, form_data: Dict) -> DataSchemaSection:
        section = DataSchemaSection(
            schema=schema,
            key=form_data['key'],
            label=form_data['label'],
            description=form_data.get('description') or None,
            position=form_data.get('position') or 0,
            active=form_data.get('active', True),
        )
        db.session.add(section)
        db.session.flush()
        return section

    def update_section(self, section: DataSchemaSection, form_data: Dict) -> None:
        section.label = form_data['label']
        section.description = form_data.get('description') or None
        section.position = form_data.get('position') or 0
        section.active = form_data.get('active', True)

    def create_field(self, schema: DataSchema, section: DataSchemaSection, form_data: Dict) -> DataSchemaField:
        storage = form_data.get('storage', 'extra')
        column_name = form_data.get('storage_column') if storage == 'column' else None
        field = DataSchemaField(
            schema=schema,
            section=section,
            key=form_data['key'],
            label=form_data['label'],
            help_text=form_data.get('help_text') or None,
            field_type=form_data.get('field_type') or 'textarea',
            storage=storage,
            storage_column=column_name if storage == 'column' else None,
            position=form_data.get('position') or 0,
            required=form_data.get('required', False),
            active=form_data.get('active', True),
            placeholder=form_data.get('placeholder') or None,
            config=form_data.get('config') or {},
        )
        db.session.add(field)
        db.session.flush()
        return field

    def update_field(self, field: DataSchemaField, form_data: Dict) -> None:
        storage = form_data.get('storage', 'extra')
        column_name = form_data.get('storage_column') if storage == 'column' else None
        field.label = form_data['label']
        field.help_text = form_data.get('help_text') or None
        field.field_type = form_data.get('field_type') or 'textarea'
        field.storage = storage
        field.storage_column = column_name if storage == 'column' else None
        field.position = form_data.get('position') or 0
        field.required = form_data.get('required', False)
        field.active = form_data.get('active', True)
        field.placeholder = form_data.get('placeholder') or None

    def toggle_field(self, field: DataSchemaField, active: bool) -> None:
        field.active = active
        if not active and field.archived_at is None:
            field.archived_at = db.func.now()
        if active:
            field.archived_at = None

    # ---------------------------
    # Plan helpers
    # ---------------------------

    def build_sections(self, plan: PlanCadre, form) -> List[SectionContext]:
        schema = self.ensure_schema()
        record = DataSchemaRecord.get_or_create(schema.id, self.owner_type, plan.id)
        sections: List[SectionContext] = []
        for section in schema.sections:
            if not section.active:
                continue
            section_fields: List[FieldContext] = []
            for field in section.fields:
                if not field.is_active:
                    continue
                ctx = self._build_field_context(plan, form, record, section, field)
                if ctx:
                    section_fields.append(ctx)
            sections.append(
                SectionContext(
                    key=section.key,
                    label=section.label,
                    description=section.description,
                    position=section.position,
                    fields=section_fields,
                )
            )
        sections.sort(key=lambda s: s.position)
        return sections

    def _build_field_context(
        self,
        plan: PlanCadre,
        form,
        record: DataSchemaRecord,
        section: DataSchemaSection,
        field: DataSchemaField,
    ) -> Optional[FieldContext]:
        storage_column = field.storage_column if field.storage == 'column' else None
        form_field = None
        html_name = field.key
        html_id = field.key
        value = None
        improve_target = None
        if field.storage == 'column':
            attr_name = storage_column or field.key
            form_field = getattr(form, attr_name, None) if form is not None else None
            value = getattr(plan, attr_name, None)
            if form_field is not None:
                html_name = form_field.name
                html_id = form_field.id
            else:
                html_name = attr_name
                html_id = attr_name
            improve_target = attr_name
        else:
            value = (record.data or {}).get(field.key)
            html_name = f"extra__{field.key}"
            html_id = html_name

        return FieldContext(
            key=field.key,
            label=field.label,
            storage=field.storage,
            section_key=section.key,
            html_name=html_name,
            html_id=html_id,
            field_type=field.field_type or 'textarea',
            help_text=field.help_text,
            placeholder=field.placeholder,
            required=field.required,
            storage_column=storage_column,
            form_field=form_field,
            improve_target=improve_target,
            value=value,
        )

    def record_for_plan(self, plan: PlanCadre) -> DataSchemaRecord:
        schema = self.ensure_schema()
        return DataSchemaRecord.get_or_create(schema.id, self.owner_type, plan.id)

    def update_extra_fields(self, plan: PlanCadre, sections: List[SectionContext], form_data) -> None:
        record = self.record_for_plan(plan)
        payload = dict(record.data or {})
        changed = False
        for section in sections:
            for field in section.fields:
                if field.storage != 'extra':
                    continue
                value = form_data.get(field.html_name, '')
                # Normalize whitespace for comparison to reduce needless commits
                if value != payload.get(field.key):
                    payload[field.key] = value
                    changed = True
        if changed:
            record.data = payload
            db.session.add(record)


class PlanCadreSchemaManager(SchemaManager):
    slug = 'plan_cadre'
    owner_type = 'PlanCadre'

    @property
    def default_name(self) -> str:
        return "Plan-cadre"

    @property
    def default_description(self) -> str:
        return "Sections textuelles configurables pour les plans-cadres."

    def default_sections(self) -> Iterable[Dict]:
        return [
            {
                'key': 'repere_generaux',
                'label': 'Repères généraux',
                'position': 10,
                'fields': [
                    {
                        'key': 'place_intro',
                        'label': 'Place et rôle du cours dans le programme',
                        'storage': 'column',
                        'storage_column': 'place_intro',
                        'position': 10,
                    },
                ],
            },
            {
                'key': 'resultats_vises',
                'label': 'Résultats visés',
                'position': 15,
                'fields': [
                    {
                        'key': 'objectif_terminal',
                        'label': 'Objectif terminal du cours',
                        'storage': 'column',
                        'storage_column': 'objectif_terminal',
                        'position': 10,
                    },
                ],
            },
            {
                'key': 'organisation_apprentissage',
                'label': "Organisation de l'apprentissage",  # title shown in accordion
                'position': 20,
                'fields': [
                    {
                        'key': 'structure_intro',
                        'label': 'Structure du cours',
                        'storage': 'column',
                        'storage_column': 'structure_intro',
                        'position': 10,
                    },
                    {
                        'key': 'structure_activites_theoriques',
                        'label': 'Activités théoriques',
                        'storage': 'column',
                        'storage_column': 'structure_activites_theoriques',
                        'position': 20,
                    },
                    {
                        'key': 'structure_activites_pratiques',
                        'label': 'Activités pratiques',
                        'storage': 'column',
                        'storage_column': 'structure_activites_pratiques',
                        'position': 30,
                    },
                    {
                        'key': 'structure_activites_prevues',
                        'label': 'Activités prévues',
                        'storage': 'column',
                        'storage_column': 'structure_activites_prevues',
                        'position': 40,
                    },
                ],
            },
            {
                'key': 'evaluation',
                'label': 'Évaluation des apprentissages',
                'position': 30,
                'fields': [
                    {
                        'key': 'eval_evaluation_sommative',
                        'label': 'Évaluation sommative des apprentissages',
                        'storage': 'column',
                        'storage_column': 'eval_evaluation_sommative',
                        'position': 10,
                    },
                    {
                        'key': 'eval_nature_evaluations_sommatives',
                        'label': 'Nature des évaluations sommatives',
                        'storage': 'column',
                        'storage_column': 'eval_nature_evaluations_sommatives',
                        'position': 20,
                    },
                    {
                        'key': 'eval_evaluation_de_la_langue',
                        'label': 'Évaluation de la langue',
                        'storage': 'column',
                        'storage_column': 'eval_evaluation_de_la_langue',
                        'position': 30,
                    },
                    {
                        'key': 'eval_evaluation_sommatives_apprentissages',
                        'label': 'Évaluation sommative (CKEditor)',
                        'storage': 'column',
                        'storage_column': 'eval_evaluation_sommatives_apprentissages',
                        'position': 40,
                    },
                ],
            },
        ]

    def column_choices(self) -> List[tuple]:
        return [
            ('place_intro', 'Place et rôle du cours'),
            ('objectif_terminal', 'Objectif terminal'),
            ('structure_intro', 'Structure du cours'),
            ('structure_activites_theoriques', 'Activités théoriques'),
            ('structure_activites_pratiques', 'Activités pratiques'),
            ('structure_activites_prevues', 'Activités prévues'),
            ('eval_evaluation_sommative', 'Évaluation sommative'),
            ('eval_nature_evaluations_sommatives', 'Nature des évaluations sommatives'),
            ('eval_evaluation_de_la_langue', 'Évaluation de la langue'),
            ('eval_evaluation_sommatives_apprentissages', 'Évaluation sommative (CKEditor)'),
        ]


def get_schema_manager(slug: str) -> Optional[SchemaManager]:
    if slug == 'plan_cadre':
        return PlanCadreSchemaManager()
    current_app.logger.warning("Schema manager requested for unknown slug '%s'", slug)
    return None
