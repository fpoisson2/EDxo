# app/tasks.py
import os

import re

import json
import logging
from typing import List, Optional

# Import your OpenAI client (adjust this import according to your library)
from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

# Import your models – adjust these imports as needed:
from app.models import (
    PlanCadre, GlobalGenerationSettings, Competence, ElementCompetence,
    ElementCompetenceParCours, CoursCorequis, Cours, CoursPrealable,
    PlanCadreSavoirEtre, PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires, PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation, User, Programme
)

from celery import shared_task 
from celery_app import celery  # Your Celery instance (configured with your Flask app)
from extensions import db  # Your SQLAlchemy instance
from utils.openai_pricing import calculate_call_cost
# Import any helper functions used in your logic
from utils.utils import replace_tags_jinja2, get_plan_cadre_data, determine_base_filename, extract_code_from_title

from ocr_processing import api_clients, pdf_tools, web_utils

from config.constants import *

from flask import current_app 

logger = logging.getLogger(__name__)

###############################################################################
# Schemas Pydantic pour IA
###############################################################################
def _postprocess_openai_schema(schema: dict) -> None:
    schema.pop('default', None)
    schema['additionalProperties'] = False

    props = schema.get("properties")
    if props:
        schema["required"] = list(props.keys())
        for prop_schema in props.values():
            _postprocess_openai_schema(prop_schema)

    if "items" in schema:
        items = schema["items"]
        if isinstance(items, dict):
            _postprocess_openai_schema(items)
        elif isinstance(items, list):
            for item in items:
                _postprocess_openai_schema(item)

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

class PlanCadreAIResponse(OpenAIFunctionModel):
    fields: Optional[List[AIField]] = None
    fields_with_description: Optional[List[AIFieldWithDescription]] = None
    savoir_etre: Optional[List[str]] = None
    capacites: Optional[List[AICapacite]] = None

@celery.task(bind=True)
def generate_plan_cadre_content_task(self, plan_id, form_data, user_id):
    """
    Celery task to generate the content of a plan-cadre via GPT.

    This task:
      - Retrieves the PlanCadre and User data.
      - Checks for a valid OpenAI key and sufficient user credits.
      - Saves additional info and ai_model from the form.
      - Prepares data from GlobalGenerationSettings and the plan.
      - Depending on whether each section is flagged for AI or not, builds
        prompts or directly updates/inserts content into the database.
      - Calls the OpenAI API once (using the responses endpoint with structured output)
        to generate content.
      - Computes token usage, cost, updates the user’s credits,
        and then stores the generated content in the database.

    Parameters:
      - plan_id (int): The ID of the plan.
      - form_data (dict): Dictionary of form values (e.g., additional_info, ai_model, etc.).
      - user_id (int): The ID of the user initiating the generation.

    Returns:
      dict: A dictionary with keys 'status' and 'message'.
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
        additional_info = form_data.get("additional_info", "")
        ai_model = form_data.get("ai_model", "")

        # Save additional info and the AI model in the plan
        plan.additional_info = additional_info
        plan.ai_model = ai_model
        db.session.commit()

        # ----------------------------------------------------------------
        # 1) Prepare data and settings
        # ----------------------------------------------------------------
        cours_nom = plan.cours.nom if plan.cours else "Non défini"
        cours_session = plan.cours.session if (plan.cours and plan.cours.session) else "Non défini"

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

        def replace_jinja(text_):
            return replace_tags_jinja2(text_, plan_cadre_data)

        # Parcours des paramètres de génération
        for section_name, conf_data in parametres_dict.items():
            raw_text = str(conf_data.get('text_content', "") or "")
            replaced_text = replace_jinja(raw_text)
            is_ai = (conf_data.get('use_ai', 0) == 1)

            if section_name in field_to_plan_cadre_column:
                col_name = field_to_plan_cadre_column[section_name]
                if is_ai:
                    ai_fields.append({"field_name": section_name, "prompt": replaced_text})
                else:
                    non_ai_updates_plan_cadre.append((col_name, replaced_text))

            elif section_name in field_to_table_insert:
                table_name = field_to_table_insert[section_name]

                if section_name == "Objets cibles" and is_ai:
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

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
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

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
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

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
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

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
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if not is_ai:
                    non_ai_inserts_other_table.append((table_name, replaced_text))

            else:
                target_sections = [
                    'Capacité et pondération',
                    "Savoirs nécessaires d'une capacité",
                    "Savoirs faire d'une capacité",
                    "Moyen d'évaluation d'une capacité"
                ]
                if section_name == 'Savoir-être':
                    if is_ai:
                        ai_savoir_etre = replaced_text
                    else:
                        lines = [l.strip() for l in replaced_text.split("\n") if l.strip()]
                        for line in lines:
                            se_obj = PlanCadreSavoirEtre(plan_cadre_id=plan.id, texte=line)
                            db.session.add(se_obj)
                elif section_name in target_sections:
                    if is_ai:
                        section_formatted = f"### {section_name}\n{replaced_text}"
                        ai_capacites_prompt.append(section_formatted)
                # Les autres sections sont ignorées

        # Appliquer les mises à jour non-AI sur le plan
        for col_name, val in non_ai_updates_plan_cadre:
            setattr(plan, col_name, val)

        # Exécuter les insertions non-AI dans les autres tables
        for table_name, val in non_ai_inserts_other_table:
            db.session.execute(
                text(f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (:pcid, :val)"),
                {"pcid": plan.id, "val": val}
            )

        db.session.commit()

        # Si aucune génération AI n'est requise, on retourne tôt
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            return {"status": "success", "message": "Aucune génération IA requise (tous champs sont en mode non-AI)."}

        # ----------------------------------------------------------------
        # 2) Appel unique à l'API OpenAI (endpoint responses)
        # ----------------------------------------------------------------
        # Prépare le schéma JSON (en respectant le plan de réponse structuré)
        schema_json = json.dumps(PlanCadreAIResponse.schema(), indent=4, ensure_ascii=False)

        # Combine toutes les instructions en une seule chaîne
        combined_instruction = (
            f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', session {cours_session}. "
            f"Informations importantes à considérer avant tout: {additional_info}\n\n"
            "Voici le schéma JSON auquel ta réponse doit strictement adhérer :\n\n"
            f"{schema_json}\n\n"
            "Utilise un langage neutre (par exemple, 'étudiant' => 'personne étudiante').\n\n"
            "Si tu utilises des guillemets, utilise des guillemets français '«' et '»'\n\b"
            "Voici différents prompts :\n"
            f"- fields: {ai_fields}\n\n"
            f"- fields_with_description: {ai_fields_with_description}\n\n"
            f"- savoir_etre: {ai_savoir_etre}\n\n"
            f"- capacites: {ai_capacites_prompt}\n\n"
            "Retourne un JSON valide correspondant à PlanCadreAIResponse."
        )

        print(combined_instruction)
        # Initialise le client OpenAI avec la clé de l'utilisateur
        client = OpenAI(api_key=openai_key)
        total_prompt_tokens = 0
        total_completion_tokens = 0

        try:
            response = client.responses.create(
                model=ai_model,
                input=[
                    {"role": "system",
                     "content": f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', session {cours_session}. Informations importantes: {additional_info}"},
                    {"role": "user", "content": combined_instruction}
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "PlanCadreAIResponse",
                        "schema": PlanCadreAIResponse.schema(),
                        "strict": True
                    }
                },
                store=True,
                # Other parameters as needed (e.g., temperature, top_p, etc.)
            )
        except Exception as e:
            logging.error(f"OpenAI error: {e}")
            return {"status": "error", "message": f"Erreur API OpenAI: {str(e)}"}

        if hasattr(response, 'usage'):
            total_prompt_tokens += response.usage.input_tokens
            total_completion_tokens += response.usage.output_tokens

        # Calcul du coût total de l'appel
        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        total_cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)

        logging.info(
            f"Appel OpenAI ({ai_model}): {total_cost:.6f}$ ({usage_prompt} prompt, {usage_completion} completion)")

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
        # On suppose que la réponse structurée est dans response.choices[0].message.parsed
        parsed_json = json.loads(response.output_text)
        parsed_data = PlanCadreAIResponse(**parsed_json)

        def clean_text(val):
            return val.strip().strip('"').strip("'") if val else ""

        # Mise à jour du plan pour les champs directement dans PlanCadre
        for fobj in (parsed_data.fields or []):
            fname = fobj.field_name
            fcontent = clean_text(fobj.content)
            if fname in field_to_plan_cadre_column:
                col = field_to_plan_cadre_column[fname]
                setattr(plan, col, fcontent)

        table_mapping = {
            "Description des compétences développées": "PlanCadreCompetencesDeveloppees",
            "Description des Compétences certifiées": "PlanCadreCompetencesCertifiees",
            "Description des cours corequis": "PlanCadreCoursCorequis",
            "Description des cours préalables": "PlanCadreCoursPrealables",
            "Objets cibles": "PlanCadreObjetsCibles"
        }

        # Insertion dans d'autres tables pour les champs avec description
        for fobj in (parsed_data.fields_with_description or []):
            fname = fobj.field_name
            if not fname:
                continue

            table_name = table_mapping.get(fname)
            if not table_name:
                continue

            elements_to_insert = []
            if isinstance(fobj.content, list):
                for item in fobj.content:
                    texte_comp = clean_text(item.texte) if item.texte else ""
                    desc_comp = clean_text(item.description) if item.description else ""
                    if texte_comp or desc_comp:
                        elements_to_insert.append((texte_comp, desc_comp))
            elif isinstance(fobj.content, str):
                elements_to_insert.append((clean_text(fobj.content), ""))

            for (texte_comp, desc_comp) in elements_to_insert:
                if not texte_comp and not desc_comp:
                    continue
                db.session.execute(
                    text(f"""
                        INSERT OR REPLACE INTO {table_name} (plan_cadre_id, texte, description)
                        VALUES (:pid, :txt, :desc)
                    """),
                    {"pid": plan.id, "txt": texte_comp, "desc": desc_comp}
                )

        # Traitement du savoir-être
        if parsed_data.savoir_etre:
            for se_item in parsed_data.savoir_etre:
                se_obj = PlanCadreSavoirEtre(
                    plan_cadre_id=plan.id,
                    texte=clean_text(se_item)
                )
                db.session.add(se_obj)

        # Traitement des capacités et de leurs éléments
        if parsed_data.capacites:
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

        db.session.commit()

        result = {
            "status": "success",
            "message": f"Contenu généré automatiquement avec succès! Coût total: {round(total_cost, 4)} crédits.",
            "plan_id": plan.id,
            "cours_id": plan.cours_id
        }
        self.update_state(state='SUCCESS', meta=result)
        return result

    except Exception as e:
        db.session.rollback()
        logging.error("Unexpected error: %s", e, exc_info=True)
        return {"status": "error", "message": f"Erreur lors de la génération du contenu: {str(e)}"}

@shared_task(bind=True)
def process_ocr_task(self, pdf_source, pdf_title, user_id, openai_key):
    """
    Traite un document PDF en :
      - Téléchargeant le PDF (ou utilisant un fichier local)
      - Effectuant l'OCR pour générer un Markdown
      - Utilisant OpenAI pour segmenter la section "Formation spécifique"
        et obtenir pour chaque compétence le code et les bornes de pages
      - Pour chaque compétence, extrait le texte correspondant et appelle
        l'extraction JSON via extraire_competences_depuis_txt.
      - Calcule le coût des appels OpenAI et déduit le coût des crédits de l'utilisateur.
      - Enregistre le JSON final contenant la liste complète des compétences.
      
    Retourne un dict contenant le statut et le message.
    """

    def update_progress(stage, message, progress, details=None):
        meta = {
            'step': stage,
            'message': message,
            'progress': progress,
            'task_id': self.request.id
        }
        if details:
            meta['details'] = details
        self.update_state(state='PROGRESS', meta=meta)

    # Récupérer l'utilisateur pour obtenir sa clé et ses crédits
    user = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
    if not user:
        return {"status": "error", "message": "Utilisateur introuvable."}
    # Overwrite openai_key with the one stored for the user (if needed)
    openai_key = user.openai_key
    user_credits = user.credits

    if not openai_key:
        error_msg = "Aucune clef d'API configurée."
        raise ValueError(error_msg)
    if user_credits <= 0:
        error_msg = "Vous n’avez plus de crédits pour effectuer un appel OpenAI."
        raise ValueError(error_msg)

    task_id = self.request.id
    update_progress("Initialisation", "Démarrage de la tâche...", 0)

    logger.info(f"[{task_id}] Démarrage du traitement OCR pour: {pdf_title} ({pdf_source})")

    try:
        pdf_output_dir = current_app.config.get('PDF_OUTPUT_DIR', 'pdfs_downloaded')
        txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR')
        os.makedirs(pdf_output_dir, exist_ok=True)
        os.makedirs(txt_output_dir, exist_ok=True)
    except Exception as config_err:
        logger.critical(f"[{task_id}] Erreur critique: Impossible d'accéder à la configuration ou de créer des répertoires: {config_err}", exc_info=True)
        update_progress("Erreur configuration", f"Erreur de configuration: {config_err}", 0)
        return {'task_id': task_id, 'final_status': 'FAILURE', 'error': f"Erreur de configuration: {config_err}"}

    results = {
        'task_id': task_id,
        'pdf_title': pdf_title,
        'pdf_source': pdf_source,
        'base_filename': None,
        'final_status': "In Progress",
        'error': None,
        'download_path': None,
        'ocr_markdown_path': None,
        'section_info': None,
        'section_pdf_path': None,
        'txt_output_path': None,
        'json_output_path': None,
        'competences_count': 0,
        'openai_cost': 0.0,
        'usage_details': {}
    }

    # Variables de travail locales
    download_path_local = None
    ocr_markdown_path_local = None
    json_output_path_local = None
    base_filename_local = None
    final_status_internal = "FAILURE"

    try:
        # --- Étape 0 : Déterminer le nom de fichier de base ---
        base_filename_local = determine_base_filename(extract_code_from_title(pdf_title), pdf_title)
        if not base_filename_local:
            raise ValueError(f"Impossible de déterminer un nom de fichier de base pour: {pdf_title}")
        results['base_filename'] = base_filename_local
        logger.info(f"[{task_id}] Base Filename déterminé: {base_filename_local}")
        update_progress("Détermination", "Étape 0/5 - Nom de fichier déterminé", 10)

        # --- Étape 1: Téléchargement (si nécessaire) ---
        if pdf_source.startswith('http://') or pdf_source.startswith('https://'):
            update_progress("Téléchargement", "Étape 1/5 - Téléchargement du PDF...", 15, f"URL: {pdf_source}")
            download_path_local = web_utils.telecharger_pdf(pdf_source, pdf_output_dir)
            if not download_path_local or not os.path.exists(download_path_local):
                raise RuntimeError(f"Échec du téléchargement ou chemin invalide retourné pour {pdf_source}")
            results['download_path'] = download_path_local
            logger.info(f"[{task_id}] PDF téléchargé vers: {download_path_local}")
        elif os.path.exists(pdf_source):
            download_path_local = pdf_source
            results['download_path'] = download_path_local
            logger.info(f"[{task_id}] Utilisation du fichier local existant: {download_path_local}")
        else:
            raise FileNotFoundError(f"Source PDF invalide (ni URL, ni chemin existant): {pdf_source}")
        update_progress("Téléchargement", "PDF téléchargé", 25)

        # --- Étape 2: OCR Complet ---
        update_progress("OCR", "Étape 2/5 - Lancement de l'OCR complet...", 30, "Conversion du PDF en Markdown")
        ocr_markdown_path_local = os.path.join(txt_output_dir, f"{base_filename_local}_ocr.md")
        try:
            ocr_input_source = pdf_source if pdf_source.startswith('http') else download_path_local
            logger.info(f"[{task_id}] Appel de perform_ocr_and_save avec la source: {ocr_input_source}")
            ocr_success = api_clients.perform_ocr_and_save(ocr_input_source, ocr_markdown_path_local)
            if not ocr_success:
                raise RuntimeError("L'étape OCR a échoué (perform_ocr_and_save a retourné False/None).")
            results['ocr_markdown_path'] = ocr_markdown_path_local
            logger.info(f"[{task_id}] OCR Markdown généré: {ocr_markdown_path_local}")
        except Exception as ocr_err:
            logger.error(f"[{task_id}] Erreur lors de l'OCR: {ocr_err}", exc_info=True)
            raise RuntimeError(f"Échec de l'OCR: {ocr_err}")
        update_progress("OCR", "OCR terminé", 40)

        # --- Étape 3: Identification et segmentation des compétences ---
        update_progress("Segmentation", "Étape 3/5 - Début de la segmentation des compétences...", 45, "Analyse de la section 'Formation spécifique'")
        try:
            with open(ocr_markdown_path_local, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
        except Exception as read_err:
            logger.error(f"[{task_id}] Erreur lecture fichier Markdown {ocr_markdown_path_local}: {read_err}", exc_info=True)
            raise RuntimeError(f"Erreur lecture fichier OCR: {read_err}")

        try:
            competence_pages_info = api_clients.find_competences_pages(markdown_content, openai_key)
        except Exception as seg_err:
            logger.error(f"[{task_id}] Erreur lors de la segmentation des compétences : {seg_err}")
            competence_pages_info = None

        if competence_pages_info and "competences" in competence_pages_info:
            results["competences_pages"] = competence_pages_info["competences"]
            logger.info(f"[{task_id}] Compétences identifiées : {competence_pages_info['competences']}")
        else:
            logger.warning(f"[{task_id}] Aucune segmentation de compétences n'a été identifiée par l'IA.")
            results["competences_pages"] = []
        update_progress("Segmentation", "Segmentation terminée", 50)

        # --- Étape 4: Extraction JSON pour chaque compétence ---
        json_output_path_local = os.path.join(txt_output_dir, f"{base_filename_local}_competences.json")
        all_competences = []
        if results.get("competences_pages"):
            total_competences = len(results["competences_pages"])
            for idx, comp in enumerate(results["competences_pages"], start=1):
                code_comp = comp.get("code")
                page_debut = comp.get("page_debut")
                page_fin = comp.get("page_fin")

                competence_pdf_path = os.path.join(pdf_output_dir, f"{base_filename_local}_competence_{code_comp}.pdf")
                if not pdf_tools.extract_pdf_section(download_path_local, competence_pdf_path, page_debut, page_fin):
                    raise RuntimeError("L'extraction du PDF d'une compétence a échoué")
                results['competence_pdf_path'] = competence_pdf_path
                logger.info(f"[{task_id}] Section PDF de la compétence {code_comp} extraite: {competence_pdf_path}")

                competence_txt_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences_{code_comp}.txt")
                competence_text = pdf_tools.convert_pdf_to_txt(competence_pdf_path, competence_txt_path)
                if not competence_text.strip():
                    raise RuntimeError("La conversion en texte de la compétence est vide.")
                results['txt_output_path'] = competence_txt_path
                logger.info(f"[{task_id}] Texte de la compétence {code_comp} généré: {competence_txt_path}")

                if not competence_text:
                    logger.warning(f"[{task_id}] Aucun texte extrait pour la compétence {code_comp} (pages {page_debut}-{page_fin}).")
                    continue
                try:
                    extraction_output = api_clients.extraire_competences_depuis_txt(
                        competence_text, json_output_path_local, openai_key
                    )
                    competence_json_str = extraction_output.get("result")
                    try:
                        comp_data = json.loads(competence_json_str)
                        if "competences" in comp_data:
                            for item in comp_data["competences"]:
                                if not item.get("Code"):
                                    item["Code"] = code_comp
                                all_competences.append(item)
                    except Exception as json_e:
                        logger.error(f"[{task_id}] Erreur JSON pour la compétence {code_comp}: {json_e}")
                except Exception as e:
                    logger.error(f"[{task_id}] Erreur lors de l'extraction d'une compétence {code_comp}: {e}")
                update_progress("Extraction JSON", f"Extraction JSON pour la compétence {code_comp} ({idx}/{total_competences})", 50 + int(45 * idx / total_competences), f"Pages {page_debut}-{page_fin}")
            results['competences_count'] = len(all_competences)
        else:
            logger.warning(f"[{task_id}] Aucune segmentation de compétences trouvée. L'extraction JSON sera tentée sur le document complet.")
            try:
                extraction_output = api_clients.extraire_competences_depuis_txt(markdown_content, json_output_path_local, openai_key)
                competence_json_str = extraction_output.get("result")
                comp_data = json.loads(competence_json_str)
                all_competences = comp_data.get("competences", [])
                results['competences_count'] = len(all_competences)
            except Exception as e:
                logger.error(f"[{task_id}] Erreur lors de l'extraction JSON sur l'ensemble du document: {e}")
                results['competences_count'] = 0

        # Sauvegarde finale du JSON rassemblé
        final_competences = {"competences": all_competences}
        try:
            with open(json_output_path_local, "w", encoding="utf-8") as f:
                json.dump(final_competences, f, ensure_ascii=False, indent=4)
            results['json_output_path'] = json_output_path_local
            logger.info(f"[{task_id}] Extraction JSON réussie: {results['competences_count']} compétences. Fichier: {json_output_path_local}")
        except Exception as save_err:
            logger.error(f"[{task_id}] Erreur lors de la sauvegarde du JSON final: {save_err}")
            results['json_output_path'] = None

        update_progress("Extraction JSON", "Extraction JSON terminée", 95)

        # --- Calculer le coût des appels OpenAI ---
        from utils.openai_pricing import calculate_call_cost

        section_prompt_tokens = getattr(results.get("usage_section", {}), 'input_tokens', 0)
        section_completion_tokens = getattr(results.get("usage_section", {}), 'output_tokens', 0)
        extraction_prompt_tokens = getattr(results.get("usage_extraction", {}), 'input_tokens', 0)
        extraction_completion_tokens = getattr(results.get("usage_extraction", {}), 'output_tokens', 0)
        model_section = current_app.config.get('OPENAI_MODEL_SECTION')
        model_extraction = current_app.config.get('OPENAI_MODEL_EXTRACTION')
        cost_section = calculate_call_cost(section_prompt_tokens, section_completion_tokens, model_section)
        cost_extraction = calculate_call_cost(extraction_prompt_tokens, extraction_completion_tokens, model_extraction)
        total_cost = cost_section + cost_extraction
        results['openai_cost'] = total_cost
        results['usage_details'] = {
            "section": {
                "prompt_tokens": section_prompt_tokens,
                "completion_tokens": section_completion_tokens,
            },
            "extraction": {
                "prompt_tokens": extraction_prompt_tokens,
                "completion_tokens": extraction_completion_tokens,
            }
        }
        logger.info(f"[{task_id}] Coût OpenAI total pour OCR: {total_cost:.6f} crédits")

        if user_credits < total_cost:
            raise ValueError("Crédits insuffisants pour effectuer les appels OpenAI.")

        # Déduire le coût des crédits de l'utilisateur
        new_credits = user_credits - total_cost
        db.session.execute(
            text("UPDATE User SET credits = :credits WHERE id = :uid"),
            {"credits": new_credits, "uid": user_id}
        )
        db.session.commit()

        # --- Finalisation ---
        if results.get("ocr_markdown_path") and results.get("json_output_path") and results.get("competences_count", 0) > 0:
            final_status_internal = "SUCCESS"
        elif results.get("ocr_markdown_path") and results.get("json_output_path") and results.get("competences_count", 0) == 0:
            final_status_internal = "COMPLETED_WITH_JSON_EMPTY"
            logger.warning(f"[{task_id}] Traitement terminé mais le JSON de compétences est vide.")
        elif results.get("ocr_markdown_path"):
            final_status_internal = "COMPLETED_WITH_OCR_ONLY"
            logger.warning(f"[{task_id}] Traitement terminé mais sans extraction JSON valide/réussie.")
        else:
            final_status_internal = "FAILURE"
            results["error"] = results.get("error") or "Échec de l'étape OCR initiale."

        results["final_status"] = final_status_internal
        logger.info(f"[{task_id}] Traitement terminé avec statut: {final_status_internal}")

    except Exception as e:
        db.session.rollback()
        logger.critical(f"[{task_id}] Erreur majeure et inattendue dans la tâche process_ocr_task: {e}", exc_info=True)
        results["final_status"] = "FAILURE"
        results["error"] = f"Erreur inattendue: {e}"

    # --- Retourner les résultats avec la progression finale ---
    self.update_state(
        state=results['final_status'] if results['final_status'] != "FAILURE" else "FAILURE",
        meta={**results, 'progress': 100}
    )
    return results
