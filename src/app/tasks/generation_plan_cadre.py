# app/tasks.py
import os
import re
import json
import logging
from typing import List, Optional

# Import your OpenAI client (adjust this import according to your library)
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import text

# Import your models – adjust these imports as needed:
from ..models import (
    PlanCadre, GlobalGenerationSettings, Competence, ElementCompetence,
    ElementCompetenceParCours, CoursCorequis, Cours, CoursPrealable,
    PlanCadreSavoirEtre, PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires, PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation, User, Programme
)

from celery import shared_task, group, signature
from celery_app import celery  # Your Celery instance (configured with your Flask app)
from extensions import db  # Your SQLAlchemy instance
from utils.openai_pricing import calculate_call_cost
# Import any helper functions used in your logic
from utils.utils import replace_tags_jinja2, get_plan_cadre_data, determine_base_filename, extract_code_from_title
from ocr_processing import api_clients, pdf_tools, web_utils
from config.constants import *
from flask import current_app 
from celery.exceptions import Ignore
from celery import chord

logger = logging.getLogger(__name__)

###############################################################################
# Schemas Pydantic pour IA
###############################################################################
def _postprocess_openai_schema(schema: dict) -> None:
    """Recursively tailor a Pydantic schema for OpenAI JSON responses."""
    schema.pop('default', None)

    # $ref nodes cannot have siblings like "additionalProperties"; stop here
    if '$ref' in schema:
        return

    # Only apply object-specific keywords to object schemas
    if schema.get('type') == 'object' or 'properties' in schema:
        schema['additionalProperties'] = False

    props = schema.get('properties')
    if props:
        schema['required'] = list(props.keys())
        for prop_schema in props.values():
            _postprocess_openai_schema(prop_schema)

    if 'items' in schema:
        items = schema['items']
        if isinstance(items, dict):
            _postprocess_openai_schema(items)
        elif isinstance(items, list):
            for item in items:
                _postprocess_openai_schema(item)

    # Recurse into definitions if present
    if '$defs' in schema:
        for def_schema in schema['$defs'].values():
            _postprocess_openai_schema(def_schema)

class OpenAIFunctionModel(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        json_schema_extra=lambda schema, _: _postprocess_openai_schema(schema)
    )

class AIField(OpenAIFunctionModel):
    field_name: Optional[str] = None
    content: Optional[str] = None

class AIContentDetail(OpenAIFunctionModel):
    texte: Optional[str] = None
    description: Optional[str] = None

class AIFieldWithDescription(OpenAIFunctionModel):
    field_name: Optional[str] = None
    content: Optional[List[AIContentDetail]] = None

class AISavoirFaire(OpenAIFunctionModel):
    texte: Optional[str] = None
    cible: Optional[str] = None
    seuil_reussite: Optional[str] = None

class AICapacite(OpenAIFunctionModel):
    capacite: Optional[str] = None
    description_capacite: Optional[str] = None
    ponderation_min: Optional[int] = None
    ponderation_max: Optional[int] = None
    savoirs_necessaires: Optional[List[str]] = None
    savoirs_faire: Optional[List[AISavoirFaire]] = None
    moyens_evaluation: Optional[List[str]] = None


# Register with a stable, fully-qualified name so producers and workers match
@celery.task(bind=True, name='src.app.tasks.generation_plan_cadre.generate_plan_cadre_content_task')
def generate_plan_cadre_content_task(self, plan_id, form_data, user_id):
    """
    Celery task to generate the content of a plan-cadre via GPT.
    """
    try:
        logging.info("Starting task for plan_id %s by user_id %s", plan_id, user_id)
        # Retrieve the plan
        plan = PlanCadre.query.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan Cadre non trouvé."}

        # Retrieve the user details (openai_key and credits)
        user = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
        if not user:
            return {"status": "error", "message": "Utilisateur introuvable."}
        openai_key = user.openai_key
        user_credits = user.credits

        if not openai_key:
            return {"status": "error", "message": "Aucune clé OpenAI configurée dans votre profil."}
        if user_credits <= 0:
            return {"status": "error", "message": "Vous n’avez plus de crédits pour effectuer un appel OpenAI."}

        # Assume that form_data has already been validated
        mode = (form_data.get("mode") or "").strip().lower()
        additional_info = form_data.get("additional_info", "")
        ai_model = form_data.get("ai_model", "")
        improve_only = form_data.get("improve_only", False)
        target_columns = form_data.get("target_columns") or []
        if isinstance(target_columns, str):
            target_columns = [c.strip() for c in target_columns.split(',') if c.strip()]
        reasoning_effort = form_data.get("reasoning_effort") or None
        verbosity = form_data.get("verbosity") or None
        wand_instruction = form_data.get("wand_instruction") or ""

        # Si le mode baguette est activé: forcer une amélioration ciblée et un prompt minimal
        if mode == 'wand':
            improve_only = True
            # Remplacer additional_info par l'instruction courte si fournie
            if wand_instruction:
                additional_info = wand_instruction

        # Save additional info and the AI model in the plan (éviter d'écraser en mode baguette)
        if mode != 'wand':
            plan.additional_info = additional_info
            plan.ai_model = ai_model
            db.session.commit()

        # ----------------------------------------------------------------
        # 1) Prepare data and settings
        # ----------------------------------------------------------------
        # Récupérer le nom et la session du cours via l'association CoursProgramme
        cours_nom = plan.cours.nom if plan.cours else "Non défini"
        if plan.cours:
            # Première programme associé (legacy)
            primary_prog = plan.cours.programme
            if primary_prog:
                # session spécifique stockée dans la table d'association
                cours_session = plan.cours.sessions_map.get(primary_prog.id, "Non défini")
            else:
                cours_session = "Non défini"
        else:
            cours_session = "Non défini"

        # Notifier le client que la génération est en cours
        self.update_state(
            state='PROGRESS',
            meta={'message': f"Génération automatique du plan-cadre du cours {cours_nom} en cours"}
        )

        # Récupérer les paramètres globaux de génération
        parametres_generation = db.session.query(
            GlobalGenerationSettings.section,
            GlobalGenerationSettings.use_ai,
            GlobalGenerationSettings.text_content
        ).all()

        parametres_dict = {
            row.section: {
                'use_ai': row.use_ai,
                'text_content': row.text_content
            }
            for row in parametres_generation
        }

        plan_cadre_data = get_plan_cadre_data(plan.cours_id)

        field_to_plan_cadre_column = {
            'Intro et place du cours': 'place_intro',
            'Objectif terminal': 'objectif_terminal',
            'Introduction Structure du Cours': 'structure_intro',
            'Activités Théoriques': 'structure_activites_theoriques',
            'Activités Pratiques': 'structure_activites_pratiques',
            'Activités Prévues': 'structure_activites_prevues',
            'Évaluation Sommative des Apprentissages': 'eval_evaluation_sommative',
            'Nature des Évaluations Sommatives': 'eval_nature_evaluations_sommatives',
            'Évaluation de la Langue': 'eval_evaluation_de_la_langue',
            'Évaluation formative des apprentissages': 'eval_evaluation_sommatives_apprentissages',
        }

        field_to_table_insert = {
            'Description des compétences développées': 'PlanCadreCompetencesDeveloppees',
            'Description des Compétences certifiées': 'PlanCadreCompetencesCertifiees',
            'Description des cours corequis': 'PlanCadreCoursCorequis',
            'Objets cibles': 'PlanCadreObjetsCibles',
            'Description des cours reliés': 'PlanCadreCoursRelies',
            'Description des cours préalables': 'PlanCadreCoursPrealables',
        }

        # Initialisation des listes pour le traitement AI et non-AI
        ai_fields = []
        ai_fields_with_description = []
        non_ai_updates_plan_cadre = []
        non_ai_inserts_other_table = []
        ai_savoir_etre = None
        ai_capacites_prompt = []
        current_capacites_snapshot = []

        def replace_jinja(text_):
            return replace_tags_jinja2(text_, plan_cadre_data)

        def include_section(section_name: str, col_name: str = None) -> bool:
            """Return True if this section should be included given target_columns.

            - When target_columns is empty: include everything.
            - For simple text fields: include when the internal column name is targeted.
            - For collections/specials: include when the mapped logical key is targeted.
            """
            if not target_columns:
                return True
            # Match by PlanCadre column name when available (simple text fields)
            if col_name and col_name in target_columns:
                return True
            # Collections and specials: map display section names to logical keys
            logical_key_map = {
                'Description des compétences développées': 'competences_developpees',
                'Description des Compétences certifiées': 'competences_certifiees',
                'Description des cours corequis': 'cours_corequis',
                'Objets cibles': 'objets_cibles',
                'Description des cours reliés': 'cours_relies',
                'Description des cours préalables': 'cours_prealables',
                'Savoir-être': 'savoirs_etre',
                'Capacité et pondération': 'capacites',
                "Savoirs nécessaires d'une capacité": 'capacites',
                "Savoirs faire d'une capacité": 'capacites',
                "Moyen d'évaluation d'une capacité": 'capacites'
            }
            key = logical_key_map.get(section_name)
            if key and key in target_columns:
                return True
            return False

        # Parcours des paramètres de génération
        for section_name, conf_data in parametres_dict.items():
            raw_text = str(conf_data.get('text_content', "") or "")
            replaced_text = replace_jinja(raw_text)
            is_ai = (conf_data.get('use_ai', 0) == 1)

            if section_name in field_to_plan_cadre_column:
                col_name = field_to_plan_cadre_column[section_name]
                if not include_section(section_name, col_name):
                    continue
                if is_ai:
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = getattr(plan, col_name) or ""
                    ai_fields.append(entry)
                else:
                    # Si on cible des colonnes, on n'applique pas de non-AI en mode partiel
                    if target_columns:
                        pass
                    else:
                        if improve_only:
                            non_ai_updates_plan_cadre.append((col_name, replaced_text))
                        else:
                            non_ai_updates_plan_cadre.append((col_name, replaced_text))
            elif section_name in field_to_table_insert:
                table_name = field_to_table_insert[section_name]
                if not include_section(section_name):
                    continue
                if section_name == "Objets cibles" and is_ai:
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = [
                            {"texte": oc.texte, "description": oc.description}
                            for oc in plan.objets_cibles
                        ]
                    ai_fields_with_description.append(entry)
                if section_name == "Description des compétences développées" and is_ai:
                    competences = (
                        db.session.query(Competence.code, Competence.nom)
                        .join(ElementCompetence, ElementCompetence.competence_id == Competence.id)
                        .join(ElementCompetenceParCours,
                              ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
                        .filter(
                            ElementCompetenceParCours.cours_id == plan.cours_id,
                            ElementCompetenceParCours.status == 'Développé significativement'
                        )
                        .distinct()
                        .all()
                    )
                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences développées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp.code}: {comp.nom}\n"
                    else:
                        competences_text = "\n(Aucune compétence de type 'developpee' trouvée)\n"
                    replaced_text += f"\n\n{competences_text}"
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = [
                            {"texte": cd.texte, "description": cd.description}
                            for cd in plan.competences_developpees
                        ]
                    ai_fields_with_description.append(entry)
                if section_name == "Description des Compétences certifiées" and is_ai:
                    competences = (
                        db.session.query(Competence.code, Competence.nom)
                        .join(ElementCompetence, ElementCompetence.competence_id == Competence.id)
                        .join(ElementCompetenceParCours,
                              ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
                        .filter(
                            ElementCompetenceParCours.cours_id == plan.cours_id,
                            ElementCompetenceParCours.status == 'Atteint'
                        )
                        .distinct()
                        .all()
                    )
                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences certifiées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp.code}: {comp.nom}\n"
                    else:
                        competences_text = "\n(Aucune compétence 'certifiée' trouvée)\n"
                    replaced_text += f"\n\n{competences_text}"
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = [
                            {"texte": cc.texte, "description": cc.description}
                            for cc in plan.competences_certifiees
                        ]
                    ai_fields_with_description.append(entry)
                if section_name == "Description des cours corequis" and is_ai:
                    corequis_data = (
                        db.session.query(CoursCorequis.id, Cours.code, Cours.nom)
                        .join(Cours, CoursCorequis.cours_corequis_id == Cours.id)
                        .filter(CoursCorequis.cours_id == plan.cours_id)
                        .all()
                    )
                    cours_text = ""
                    if corequis_data:
                        cours_text = "\nListe des cours corequis:\n"
                        for c in corequis_data:
                            cours_text += f"- {c.code}: {c.nom}\n"
                    else:
                        cours_text = "\n(Aucun cours corequis)\n"
                    replaced_text += f"\n\n{cours_text}"
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = [
                            {"texte": cc.texte, "description": cc.description}
                            for cc in plan.cours_corequis
                        ]
                    ai_fields_with_description.append(entry)
                if section_name == "Description des cours préalables" and is_ai:
                    prealables_data = (
                        db.session.query(CoursPrealable.id, Cours.code, Cours.nom, CoursPrealable.note_necessaire)
                        .join(Cours, CoursPrealable.cours_id == Cours.id)
                        .filter(CoursPrealable.cours_prealable_id == plan.cours_id)
                        .all()
                    )
                    cours_text = ""
                    if prealables_data:
                        cours_text = "\nCe cours est un prérequis pour:\n"
                        for c in prealables_data:
                            note = f" (note requise: {c.note_necessaire}%)" if c.note_necessaire else ""
                            cours_text += f"- {c.code}: {c.nom}{note}\n"
                    else:
                        cours_text = "\n(Ce cours n'est prérequis pour aucun autre cours)\n"
                    replaced_text += f"\n\n{cours_text}"
                    entry = {"field_name": section_name, "prompt": replaced_text}
                    if improve_only:
                        entry["current_content"] = [
                            {"texte": cp.texte, "description": cp.description}
                            for cp in plan.cours_prealables
                        ]
                    ai_fields_with_description.append(entry)
                if not is_ai:
                    if target_columns:
                        pass
                    else:
                        if improve_only:
                            non_ai_inserts_other_table.append((table_name, replaced_text))
                        else:
                            non_ai_inserts_other_table.append((table_name, replaced_text))
            else:
                target_sections = [
                    'Capacité et pondération',
                    "Savoirs nécessaires d'une capacité",
                    "Savoirs faire d'une capacité",
                    "Moyen d'évaluation d'une capacité"
                ]
                if section_name == 'Savoir-être':
                    if not include_section(section_name):
                        continue
                    if is_ai:
                        ai_savoir_etre = replaced_text
                    else:
                        if improve_only:
                            # Reporter dans l'aperçu; pas de modification BD immédiate
                            ai_savoir_etre = replaced_text
                        else:
                            lines = [l.strip() for l in replaced_text.split("\n") if l.strip()]
                            for line in lines:
                                se_obj = PlanCadreSavoirEtre(plan_cadre_id=plan.id, texte=line)
                                db.session.add(se_obj)
                elif section_name in target_sections:
                    if not include_section(section_name):
                        continue
                    if is_ai:
                        section_formatted = f"### {section_name}\n{replaced_text}"
                        ai_capacites_prompt.append(section_formatted)
        # Préparer un instantané concis des capacités actuelles (utile en mode amélioration)
        if improve_only and (not target_columns or 'capacites' in target_columns):
            for cap in (plan.capacites or [])[:4]:  # limiter à 4 capacités pour rester concis
                current_capacites_snapshot.append({
                    'capacite': cap.capacite or '',
                    'description_capacite': (cap.description_capacite or '')[:500],
                    'ponderation_min': int(cap.ponderation_min or 0),
                    'ponderation_max': int(cap.ponderation_max or 0),
                    'savoirs_necessaires': [(sn.texte or '')[:200] for sn in list(cap.savoirs_necessaires)[:8]],
                    'savoirs_faire': [
                        {
                            'texte': (sf.texte or '')[:200],
                            'cible': (sf.cible or '')[:200],
                            'seuil_reussite': (sf.seuil_reussite or '')[:200]
                        } for sf in list(cap.savoirs_faire)[:8]
                    ],
                    'moyens_evaluation': [(me.texte or '')[:200] for me in list(cap.moyens_evaluation)[:6]]
                })
        # Appliquer les mises à jour non-AI sur le plan (sauf si mode amélioration)
        if not improve_only:
            for col_name, val in non_ai_updates_plan_cadre:
                setattr(plan, col_name, val)
            # Exécuter les insertions non-AI dans les autres tables
            for table_name, val in non_ai_inserts_other_table:
                db.session.execute(
                    text(f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (:pcid, :val)"),
                    {"pcid": plan.id, "val": val}
                )
            db.session.commit()

        # Si aucune génération AI n'est requise, retourner tôt
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            return {"status": "success", "message": "Aucune génération IA requise (tous champs sont en mode non-AI)."}

        # ----------------------------------------------------------------
        # 2) Appel unique à l'API OpenAI (endpoint responses)
        # ----------------------------------------------------------------
        # Contexte compact du cours pour aider une génération ciblée
        def clip(txt, n=600):
            txt = (txt or '')
            return (txt[:n] + '…') if len(txt) > n else txt

        context_parts = []
        # Champs principaux du plan
        if plan.place_intro:
            context_parts.append(f"Place du cours: {clip(plan.place_intro, 400)}")
        if plan.objectif_terminal:
            context_parts.append(f"Objectif terminal: {clip(plan.objectif_terminal, 300)}")
        if plan.structure_intro:
            context_parts.append(f"Intro structure: {clip(plan.structure_intro, 300)}")
        # Listes clefs (résumé)
        if plan.competences_developpees:
            cds = [cd.texte for cd in plan.competences_developpees[:5] if (cd.texte or '').strip()]
            if cds:
                context_parts.append("Compétences développées: " + "; ".join(cds))
        if plan.objets_cibles:
            ocs = [oc.texte for oc in plan.objets_cibles[:5] if (oc.texte or '').strip()]
            if ocs:
                context_parts.append("Objets cibles: " + "; ".join(ocs))

        course_context_compact = "\n".join(context_parts) or None

        # Note: The JSON schema is already enforced via the Responses API (text.format with strict schema).
        # Avoid embedding the full schema in the prompt to reduce input size.
        if mode == 'wand':
            # Prompt minimaliste et ciblé pour la baguette magique
            improve_clause = (
                "Si un 'current_content' est fourni pour la section ciblée, améliore-le. "
                "Sinon, produis un contenu complet et concis respectant le schéma demandé pour cette section. "
                "Objectifs: clarté, simplicité, concision. N'ajoute aucune information hors périmètre et ne modifie aucune autre section.\n\n"
            )
            combined_instruction = (
                f"Contexte: cours '{cours_nom}', session {cours_session}. Instruction: {additional_info}\n\n"
                f"{improve_clause}"
                "Réponds au format JSON attendu (schéma imposé par l'API).\n"
                "Prompts fournis pour les sections ciblées uniquement:\n"
                f"- fields: {ai_fields}\n\n"
                f"- fields_with_description: {ai_fields_with_description}\n\n"
                f"- savoir_etre: {ai_savoir_etre}\n\n"
                f"- capacites: {ai_capacites_prompt}\n\n"
                + (f"Contexte additionnel du cours:\n{course_context_compact}\n\n" if course_context_compact else "")
                + (f"Contenu actuel des capacités (si présent): {current_capacites_snapshot}\n" if current_capacites_snapshot else "")
                + ("Exigences pour chaque capacité: inclure 'description_capacite', une plage 'ponderation_min'/'ponderation_max',\n"
                   "au moins 5 'savoirs_necessaires', au moins 5 'savoirs_faire' (avec 'cible' et 'seuil_reussite'), et au moins 3 'moyens_evaluation'.")
            )
            system_message = (
                f"Assistant de rédaction concis. Améliore uniquement la section ciblée. Instruction: {additional_info}"
            )
        else:
            improve_clause = (
                "S'il y a un 'current_content', améliore-le. Sinon, génère un contenu approprié pour les sections ciblées. "
                "Garde la structure générale et reformule sans réécrire entièrement.\n\n"
            if improve_only
            else ""
            )
            combined_instruction = (
                f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', session {cours_session}. "
                f"Informations importantes à considérer avant tout: {additional_info}\n\n"
                f"{improve_clause}"
                "Utilise un langage neutre (par ex. 'personne étudiante').\n"
                "Si tu utilises des guillemets, utilise « » (français).\n\n"
                "Voici différents prompts (seules les sections pertinentes sont fournies) :\n"
                f"- fields: {ai_fields}\n\n"
                f"- fields_with_description: {ai_fields_with_description}\n\n"
                f"- savoir_etre: {ai_savoir_etre}\n\n"
                f"- capacites: {ai_capacites_prompt}\n\n"
                + (f"Contexte additionnel du cours:\n{course_context_compact}\n\n" if course_context_compact else "")
                + (f"Contenu actuel des capacités (si présent): {current_capacites_snapshot}\n" if current_capacites_snapshot else "")
                + ("Exigences pour chaque capacité: inclure 'description_capacite', une plage 'ponderation_min'/'ponderation_max',\n"
                   "au moins 5 'savoirs_necessaires', au moins 5 'savoirs_faire' (avec 'cible' et 'seuil_reussite'), et au moins 3 'moyens_evaluation'.")
            )
            system_message = (
                f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', session {cours_session}. Informations importantes: {additional_info}"
            )
        # combined_instruction can be large; avoid noisy stdout
        logger.debug(combined_instruction)

        # Construire dynamiquement le modèle Pydantic selon les sections demandées
        model_fields = {}
        if ai_fields:
            model_fields["fields"] = (List[AIField], ...)
        if ai_fields_with_description:
            model_fields["fields_with_description"] = (List[AIFieldWithDescription], ...)
        if ai_savoir_etre:
            model_fields["savoir_etre"] = (List[str], ...)
        if ai_capacites_prompt:
            model_fields["capacites"] = (List[AICapacite], ...)
        PlanCadreAIResponse = create_model(
            "PlanCadreAIResponse", __base__=OpenAIFunctionModel, **model_fields
        )

        client = OpenAI(api_key=openai_key)
        total_prompt_tokens = 0
        total_completion_tokens = 0
        try:
            self.update_state(state='PROGRESS', meta={'message': "Appel au modèle IA en cours..."})
            text_params = {
                "format": {
                    "type": "json_schema",
                    "name": "PlanCadreAIResponse",
                    "schema": PlanCadreAIResponse.schema(),
                    "strict": True
                }
            }
            if verbosity in {"low", "medium", "high"}:
                text_params["verbosity"] = verbosity

            request_kwargs = dict(
                model=ai_model,
                input=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": combined_instruction}
                ],
                text=text_params,
                store=True,
            )
            if reasoning_effort in {"minimal", "low", "medium", "high"}:
                request_kwargs["reasoning"] = {"effort": reasoning_effort}

            # Streaming if requested by client
            do_stream = str(form_data.get("stream") or "0").lower() in ("1", "true", "yes", "on")
            streamed_text = None
            response = None
            if do_stream:
                try:
                    request_kwargs_stream = dict(request_kwargs)
                    with client.responses.stream(**request_kwargs_stream) as stream:
                        streamed_text = ""
                        seq = 0
                        for event in stream:
                            etype = getattr(event, 'type', '') or ''
                            # Primary text delta event
                            if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                                delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                                if delta:
                                    streamed_text += delta
                                    seq += 1
                                    self.update_state(state='PROGRESS', meta={
                                        'message': 'Génération en cours...',
                                        'stream_chunk': delta,
                                        'stream_buffer': streamed_text,
                                        'seq': seq
                                    })
                                    logger.info("Stream chunk %s: %s", seq, delta)
                            elif etype.endswith('response.completed') or etype == 'response.completed':
                                break
                        response = stream.get_final_response()
                except Exception as se:
                    logging.warning(f"Streaming non disponible, bascule vers mode non-stream: {se}")
                    streamed_text = None
                    response = None

            # Non-stream or fallback: perform standard request
            if streamed_text is None:
                response = client.responses.create(**request_kwargs)
        except Exception as e:
            logging.error(f"OpenAI error: {e}")
            result_meta = {"status": "error", "message": f"Erreur API OpenAI: {str(e)}"}
            self.update_state(state="SUCCESS", meta=result_meta)
            return result_meta

        if response is not None and hasattr(response, 'usage'):
            total_prompt_tokens += response.usage.input_tokens
            total_completion_tokens += response.usage.output_tokens

        usage_prompt = response.usage.input_tokens if (response is not None and hasattr(response, 'usage')) else 0
        usage_completion = response.usage.output_tokens if (response is not None and hasattr(response, 'usage')) else 0
        try:
            total_cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        except Exception as e:
            logging.warning(f"Tarification indisponible pour le modèle {ai_model}: {e}. Coût défini à 0.")
            total_cost = 0.0
        logging.info(
            f"Appel OpenAI ({ai_model}): {total_cost:.6f}$ ({usage_prompt} prompt, {usage_completion} completion)"
        )
        new_credits = user_credits - total_cost
        if new_credits < 0:
            raise ValueError("Crédits insuffisants pour effectuer l'opération")
        db.session.execute(
            text("UPDATE User SET credits = :credits WHERE id = :uid"),
            {"credits": new_credits, "uid": user_id}
        )
        db.session.commit()

        # ----------------------------------------------------------------
        # 3) Traitement de la réponse générée par l'IA
        # ----------------------------------------------------------------
        if streamed_text is not None and streamed_text.strip():
            self.update_state(state='PROGRESS', meta={'message': "Réponse reçue (stream), analyse des résultats..."})
            parsed_json = json.loads(streamed_text)
        else:
            self.update_state(state='PROGRESS', meta={'message': "Réponse reçue, analyse des résultats..."})
            parsed_json = json.loads(response.output_text)
        parsed_data = PlanCadreAIResponse(**parsed_json)

        def clean_text(val):
            return val.strip().strip('"').strip("'") if val else ""

        # Construire une proposition (aperçu) si improve_only
        proposed = {
            'fields': {},
            'fields_with_description': {},
            'capacites': []
        }

        # 3.a Champs simples
        for fobj in (getattr(parsed_data, "fields", []) or []):
            fname = fobj.field_name
            fcontent = clean_text(fobj.content)
            if fname in field_to_plan_cadre_column:
                col = field_to_plan_cadre_column[fname]
                if improve_only:
                    proposed['fields'][col] = fcontent
                else:
                    setattr(plan, col, fcontent)

        table_mapping = {
            "Description des compétences développées": "PlanCadreCompetencesDeveloppees",
            "Description des Compétences certifiées": "PlanCadreCompetencesCertifiees",
            "Description des cours corequis": "PlanCadreCoursCorequis",
            "Description des cours préalables": "PlanCadreCoursPrealables",
            "Objets cibles": "PlanCadreObjetsCibles"
        }

        # 3.b Champs avec description (listes)
        for fobj in (getattr(parsed_data, "fields_with_description", []) or []):
            fname = fobj.field_name
            if not fname:
                continue
            elements_to_insert = []
            if isinstance(fobj.content, list):
                for item in fobj.content:
                    texte_comp = clean_text(item.texte) if item.texte else ""
                    desc_comp = clean_text(item.description) if item.description else ""
                    if texte_comp or desc_comp:
                        elements_to_insert.append({"texte": texte_comp, "description": desc_comp})
            elif isinstance(fobj.content, str):
                elements_to_insert.append({"texte": clean_text(fobj.content), "description": ""})

            if improve_only:
                proposed.setdefault('fields_with_description', {})
                proposed['fields_with_description'][fname] = elements_to_insert
            else:
                table_name = table_mapping.get(fname)
                if not table_name:
                    continue
                for el in elements_to_insert:
                    db.session.execute(
                        text(f"""
                            INSERT OR REPLACE INTO {table_name} (plan_cadre_id, texte, description)
                            VALUES (:pid, :txt, :desc)
                        """),
                        {"pid": plan.id, "txt": el["texte"], "desc": el["description"]}
                    )

        # 3.c Savoir-être
        if getattr(parsed_data, "savoir_etre", None):
            if improve_only:
                proposed['savoir_etre'] = [clean_text(se_item) for se_item in parsed_data.savoir_etre]
            else:
                for se_item in parsed_data.savoir_etre:
                    se_obj = PlanCadreSavoirEtre(
                        plan_cadre_id=plan.id,
                        texte=clean_text(se_item)
                    )
                    db.session.add(se_obj)

        # 3.d Capacités
        if getattr(parsed_data, "capacites", None):
            if improve_only:
                for cap in parsed_data.capacites:
                    proposed['capacites'].append({
                        'capacite': clean_text(cap.capacite),
                        'description_capacite': clean_text(cap.description_capacite),
                        'ponderation_min': int(cap.ponderation_min) if cap.ponderation_min else 0,
                        'ponderation_max': int(cap.ponderation_max) if cap.ponderation_max else 0,
                        'savoirs_necessaires': [clean_text(sn) for sn in (cap.savoirs_necessaires or [])],
                        'savoirs_faire': [
                            {
                                'texte': clean_text(sf.texte),
                                'cible': clean_text(sf.cible),
                                'seuil_reussite': clean_text(sf.seuil_reussite)
                            } for sf in (cap.savoirs_faire or [])
                        ],
                        'moyens_evaluation': [clean_text(me) for me in (cap.moyens_evaluation or [])]
                    })
            else:
                for cap in parsed_data.capacites:
                    new_cap = PlanCadreCapacites(
                        plan_cadre_id=plan.id,
                        capacite=clean_text(cap.capacite),
                        description_capacite=clean_text(cap.description_capacite),
                        ponderation_min=int(cap.ponderation_min) if cap.ponderation_min else 0,
                        ponderation_max=int(cap.ponderation_max) if cap.ponderation_max else 0
                    )
                    db.session.add(new_cap)
                    db.session.flush()
                    if cap.savoirs_necessaires:
                        for sn in cap.savoirs_necessaires:
                            sn_obj = PlanCadreCapaciteSavoirsNecessaires(
                                capacite_id=new_cap.id,
                                texte=clean_text(sn)
                            )
                            db.session.add(sn_obj)
                    if cap.savoirs_faire:
                        for sf in cap.savoirs_faire:
                            sf_obj = PlanCadreCapaciteSavoirsFaire(
                                capacite_id=new_cap.id,
                                texte=clean_text(sf.texte),
                                cible=clean_text(sf.cible),
                                seuil_reussite=clean_text(sf.seuil_reussite)
                            )
                            db.session.add(sf_obj)
                    if cap.moyens_evaluation:
                        for me in cap.moyens_evaluation:
                            me_obj = PlanCadreCapaciteMoyensEvaluation(
                                capacite_id=new_cap.id,
                                texte=clean_text(me)
                            )
                            db.session.add(me_obj)

        if improve_only:
            # Ajouter aussi les sections non-AI préparées dans l'aperçu
            for col_name, val in non_ai_updates_plan_cadre:
                proposed['fields'][col_name] = val
            # Pour les tables avec description, stocker les valeurs textuelles telles quelles
            for table_name, val in non_ai_inserts_other_table:
                # On mappe vers les clés d'affichage connues, sinon on ignore
                reverse_map = {v: k for k, v in table_mapping.items()}
                display_key = reverse_map.get(table_name)
                if display_key:
                    proposed.setdefault('fields_with_description', {})
                    proposed['fields_with_description'][display_key] = [
                        {"texte": val, "description": ""}
                    ]

            # Nettoyer l'aperçu pour ne conserver que les sections avec contenu
            if not proposed['fields']:
                proposed.pop('fields')
            if 'fields_with_description' in proposed:
                proposed['fields_with_description'] = {
                    k: v for k, v in proposed['fields_with_description'].items() if v
                }
                if not proposed['fields_with_description']:
                    proposed.pop('fields_with_description')
            if not proposed.get('savoir_etre'):
                proposed.pop('savoir_etre', None)
            if not proposed['capacites']:
                proposed.pop('capacites')

            self.update_state(state='PROGRESS', meta={'message': "Préparation de l’aperçu des changements..."})
            result = {
                "status": "success",
                "message": f"Proposition d'amélioration générée. Coût: {round(total_cost, 4)} crédits.",
                "plan_id": plan.id,
                "cours_id": plan.cours_id,
                "preview": True,
                "proposed": proposed
            }
            if streamed_text:
                result["stream_buffer"] = streamed_text
            self.update_state(state="SUCCESS", meta=result)
            return result
        else:
            db.session.commit()
            result = {
                "status": "success",
                "message": f"Contenu généré automatiquement avec succès! Coût total: {round(total_cost, 4)} crédits.",
                "plan_id": plan.id,
                "cours_id": plan.cours_id
            }
            if streamed_text:
                result["stream_buffer"] = streamed_text
            self.update_state(state="SUCCESS", meta=result)
            return result

    except Exception as e:
        db.session.rollback()
        logging.error("Unexpected error: %s", e, exc_info=True)
        error_message = f"Erreur lors de la génération du contenu: {str(e)}"
        result_meta = {"status": "error", "message": error_message}
        self.update_state(state="SUCCESS", meta=result_meta)
        return result_meta
