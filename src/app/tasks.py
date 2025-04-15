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

        # Si aucune génération AI n'est requise, retourner tôt
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            return {"status": "success", "message": "Aucune génération IA requise (tous champs sont en mode non-AI)."}

        # ----------------------------------------------------------------
        # 2) Appel unique à l'API OpenAI (endpoint responses)
        # ----------------------------------------------------------------
        schema_json = json.dumps(PlanCadreAIResponse.schema(), indent=4, ensure_ascii=False)
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
            result_meta = {"status": "error", "message": f"Erreur API OpenAI: {str(e)}"}
            self.update_state(state="SUCCESS", meta=result_meta)
            return result_meta

        if hasattr(response, 'usage'):
            total_prompt_tokens += response.usage.input_tokens
            total_completion_tokens += response.usage.output_tokens

        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        total_cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
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
        parsed_json = json.loads(response.output_text)
        parsed_data = PlanCadreAIResponse(**parsed_json)
        def clean_text(val):
            return val.strip().strip('"').strip("'") if val else ""
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
        if parsed_data.savoir_etre:
            for se_item in parsed_data.savoir_etre:
                se_obj = PlanCadreSavoirEtre(
                    plan_cadre_id=plan.id,
                    texte=clean_text(se_item)
                )
                db.session.add(se_obj)
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
        self.update_state(state="SUCCESS", meta=result)
        return result

    except Exception as e:
        db.session.rollback()
        logging.error("Unexpected error: %s", e, exc_info=True)
        error_message = f"Erreur lors de la génération du contenu: {str(e)}"
        result_meta = {"status": "error", "message": error_message}
        self.update_state(state="SUCCESS", meta=result_meta)
        return result_meta

###############################################################################
# Tâche d'Extraction JSON par Compétence (avec logging ajouté)
###############################################################################
@shared_task(bind=True)
def extract_json_competence(self, competence, download_path_local, txt_output_dir, base_filename_local, openai_key):
    """
    Tâche de traitement pour une compétence.
    Extrait et analyse une compétence spécifique à partir d'un PDF.
    """
    task_id = self.request.id
    code_comp = competence.get("code", "NO_CODE")  # Default value
    logger.info(f"[{task_id}/{code_comp}] Démarrage extraction compétence.")
    
    try:
        # Initialisation des variables d'utilisation de l'API
        api_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": current_app.config.get('OPENAI_MODEL_EXTRACTION', 'gpt-3.5-turbo')
        }
        
        # Extraction des pages
        page_debut = competence.get("page_debut")
        page_fin = competence.get("page_fin")
        if page_debut is None or page_fin is None:
            raise ValueError(f"Pages début/fin manquantes pour compétence {code_comp}")
            
        logger.debug(f"[{task_id}/{code_comp}] Pages: {page_debut}-{page_fin}")
        
        # Détermination des chemins de fichiers
        pdf_output_dir = current_app.config.get('PDF_OUTPUT_DIR', 'pdfs_downloaded')
        competence_pdf_path = os.path.join(pdf_output_dir, f"{base_filename_local}_competence_{code_comp}.pdf")
        
        logger.info(f"[{task_id}/{code_comp}] Extraction section PDF -> {competence_pdf_path}")
        
        # Extraction de la section du PDF
        extract_success = pdf_tools.extract_pdf_section(download_path_local, competence_pdf_path, page_debut, page_fin)
        if not extract_success:
            raise RuntimeError(f"L'extraction du PDF (pages {page_debut}-{page_fin}) a échoué.")
            
        logger.info(f"[{task_id}/{code_comp}] Section PDF extraite.")
        
        # Conversion PDF -> texte
        competence_txt_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences_{code_comp}.txt")
        logger.info(f"[{task_id}/{code_comp}] Conversion PDF -> TXT -> {competence_txt_path}")
        
        competence_text = pdf_tools.convert_pdf_to_txt(competence_pdf_path, competence_txt_path)
        if not competence_text or not competence_text.strip():
            logger.warning(f"[{task_id}/{code_comp}] Conversion en texte vide ou échouée pour {competence_pdf_path}. Retourne liste vide.")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        logger.info(f"[{task_id}/{code_comp}] Conversion TXT réussie (longueur: {len(competence_text)}).")
        
        # Extraction des compétences via l'API OpenAI
        output_json_filename = os.path.join(txt_output_dir, f"{base_filename_local}_competence_{code_comp}.json")
        logger.info(f"[{task_id}/{code_comp}] Appel OpenAI pour extraction -> {output_json_filename}")
        
        try:
            extraction_output = api_clients.extraire_competences_depuis_txt(competence_text, output_json_filename, openai_key)
        except Exception as api_err:
            logger.error(f"[{task_id}/{code_comp}] Erreur API OpenAI: {api_err}", exc_info=True)
            raise SkillExtractionError(f"Erreur API OpenAI (extraction comp {code_comp}): {api_err}") from api_err
            
        logger.info(f"[{task_id}/{code_comp}] Appel API OpenAI terminé.")
        
        # Récupération des informations d'utilisation
        if isinstance(extraction_output, dict) and 'usage' in extraction_output:
            usage_info = extraction_output['usage']
            # Utiliser input_tokens pour le prompt et output_tokens pour la completion
            api_usage["prompt_tokens"] = getattr(usage_info, 'input_tokens', 0)
            api_usage["completion_tokens"] = getattr(usage_info, 'output_tokens', 0)
            logger.info(f"[{task_id}/{code_comp}] Usage API enregistré: {api_usage['prompt_tokens']} prompt, {api_usage['completion_tokens']} completion")

        # Vérification et traitement de la réponse
        if not isinstance(extraction_output, dict):
            logger.error(f"[{task_id}/{code_comp}] Retour inattendu de extraire_competences_depuis_txt: {type(extraction_output)}")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        competence_json_str = extraction_output.get("result")
        if not competence_json_str:
            logger.warning(f"[{task_id}/{code_comp}] Résultat 'result' vide ou manquant dans la réponse API OpenAI.")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        logger.info(f"[{task_id}/{code_comp}] Parsing du JSON (longueur: {len(competence_json_str)})...")
        
        try:
            comp_data = json.loads(competence_json_str)
        except json.JSONDecodeError as json_e:
            logger.error(f"[{task_id}/{code_comp}] Erreur parsing JSON: {json_e}. Contenu: {competence_json_str[:500]}...")
            raise RuntimeError(f"Erreur parsing JSON pour compétence {code_comp}: {json_e}") from json_e
            
        logger.info(f"[{task_id}/{code_comp}] Parsing JSON réussi.")
        
        if not isinstance(comp_data, dict):
            logger.error(f"[{task_id}/{code_comp}] Données JSON parsées ne sont pas un dict: {type(comp_data)}")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        competences = comp_data.get("competences", [])
        logger.debug(f"[{task_id}/{code_comp}] Compétences brutes extraites: {len(competences)}")
        
        # Enrichissement des compétences avec le code si nécessaire
        for item in competences:
            if isinstance(item, dict) and not item.get("Code"):
                item["Code"] = code_comp
            elif not isinstance(item, dict):
                logger.warning(f"[{task_id}/{code_comp}] Élément de compétence non-dict ignoré: {item}")
                
        competences = [item for item in competences if isinstance(item, dict)]
        logger.info(f"[{task_id}/{code_comp}] Traitement terminé avec succès. Retourne {len(competences)} compétence(s).")
        
        # On retourne les compétences et les informations d'utilisation
        return {
            "competences": competences,
            "code": code_comp,
            "api_usage": api_usage,
            "pages": {
                "debut": page_debut,
                "fin": page_fin
            }
        }
        
    except Exception as e:
        logger.critical(f"[{task_id}/{code_comp}] Erreur TRES INATTENDUE dans extract_json_competence: {e}", exc_info=True)
        raise e

###############################################################################
# NOUVELLE Tâche de Callback pour l'Agrégation
###############################################################################
@shared_task(bind=True)
def aggregate_ocr_results_task(self, results_list, original_task_id, json_output_path, base_filename, user_id, user_credits_initial, model_section, model_extraction, segmentation_usage_dict):
    """
    Tâche de callback pour agréger les résultats de l'extraction OCR,
    calculer les coûts et finaliser.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Démarrage agrégation pour tâche originale {original_task_id}. Reçu {len(results_list)} résultats de sous-tâches.")
    
    # Récupérer les informations originales de la tâche principale
    original_info = {}
    try:
        original_task_signature = signature('app.tasks.process_ocr_task', app=celery)
        original_task_result = original_task_signature.AsyncResult(original_task_id)
        if original_task_result.successful() and isinstance(original_task_result.result, dict):
            # Récupérer les informations importantes de la tâche principale
            original_info = original_task_result.info or {}
            logger.info(f"[{task_id}] Informations récupérées de la tâche originale: {list(original_info.keys())}")
    except Exception as fetch_err:
        logger.warning(f"[{task_id}] Impossible de récupérer les infos de la tâche originale: {fetch_err}")
    
    # Agréger les compétences et les usages
    all_competences = []
    total_extraction_prompt = 0
    total_extraction_completion = 0

    # Parcourir les résultats des sous-tâches
    for subtask_result in results_list:
        if isinstance(subtask_result, dict):
            # Nouveau format qui inclut usage et compétences
            if "competences" in subtask_result:
                all_competences.extend(subtask_result.get("competences", []))
                
                # Agréger les usages API
                api_usage = subtask_result.get("api_usage", {})
                total_extraction_prompt += api_usage.get("prompt_tokens", 0)
                total_extraction_completion += api_usage.get("completion_tokens", 0)
        elif isinstance(subtask_result, list):
            # Ancien format (juste une liste de compétences)
            all_competences.extend(subtask_result)
        else:
            logger.warning(f"[{task_id}] Résultat de sous-tâche inattendu ignoré lors de l'agrégation: {type(subtask_result)}")

    competences_count = len(all_competences)
    logger.info(f"[{task_id}] Agrégation terminée. Total compétences extraites: {competences_count}")

    # Sauvegarde du JSON final
    logger.info(f"[{task_id}] Tentative de sauvegarde du JSON final consolidé vers {json_output_path}")
    final_competences_data = {"competences": all_competences}
    final_json_saved = False
    save_error_msg = None
    
    try:
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(final_competences_data, f, ensure_ascii=False, indent=4)
        final_json_saved = True
        logger.info(f"[{task_id}] JSON final sauvegardé avec {competences_count} compétences.")
    except Exception as save_err:
        logger.error(f"[{task_id}] Erreur lors de la sauvegarde du JSON final ({json_output_path}): {save_err}", exc_info=True)
        save_error_msg = str(save_err)
    
    # Calcul des coûts d'API
    logger.info(f"[{task_id}] Calcul du coût total OpenAI...")
    total_cost = 0.0
    total_usage = {"section": {"prompt_tokens": 0, "completion_tokens": 0},
                   "extraction": {"prompt_tokens": 0, "completion_tokens": 0}}
    
    # Coût de la segmentation
    if segmentation_usage_dict and isinstance(segmentation_usage_dict, dict):
        prompt_tokens_sec = segmentation_usage_dict.get('prompt_tokens', 0)
        completion_tokens_sec = segmentation_usage_dict.get('completion_tokens', 0)
        cost_section = calculate_call_cost(prompt_tokens_sec, completion_tokens_sec, model_section)
        total_cost += cost_section
        total_usage["section"]["prompt_tokens"] = prompt_tokens_sec
        total_usage["section"]["completion_tokens"] = completion_tokens_sec
        logger.info(f"[{task_id}] Coût Segmentation ({model_section}): {cost_section:.6f} (P:{prompt_tokens_sec}, C:{completion_tokens_sec})")
    else:
        logger.warning(f"[{task_id}] Usage pour la segmentation non reçu ou invalide.")
    

    cost_extraction = calculate_call_cost(total_extraction_prompt, total_extraction_completion, model_extraction)
    total_cost += cost_extraction
    total_usage["extraction"]["prompt_tokens"] = total_extraction_prompt
    total_usage["extraction"]["completion_tokens"] = total_extraction_completion
    logger.info(f"[{task_id}] Coût Extraction réel ({model_extraction}): {cost_extraction:.6f} (P:{total_extraction_prompt}, C:{total_extraction_completion})")

    # Mise à jour des crédits utilisateur
    logger.info(f"[{task_id}] Tentative de mise à jour BDD crédits pour user {user_id}...")
    db_update_error_msg = None
    
    try:
        # Obtenir les crédits actuels
        current_user_credits = db.session.query(User.credits).filter_by(id=user_id).scalar()
        
        if current_user_credits is None:
            logger.error(f"[{task_id}] Utilisateur {user_id} non trouvé lors de la MAJ des crédits.")
            db_update_error_msg = "Utilisateur introuvable pour MAJ crédits."
        elif current_user_credits < total_cost:
            logger.warning(f"[{task_id}] Coût ({total_cost:.6f}) dépasse les crédits actuels ({current_user_credits}) de l'utilisateur {user_id}. Crédits non mis à jour négativement.")
        else:
            # Calculer les nouveaux crédits
            new_credits = current_user_credits - total_cost
            
            # Utiliser des valeurs numériques directes (et non des objets datetime)
            from datetime import datetime
            now_str = datetime.now().isoformat()
            
            # Mettre à jour les crédits
            db.session.execute(
                text("UPDATE User SET credits = :credits WHERE id = :uid"),
                {"credits": new_credits, "uid": user_id}
            )
            
            # Enregistrer le changement, mais en utilisant une requête SQL directe avec un timestamp correct
            try:
                db.session.execute(
                    text("INSERT INTO DBChange (timestamp, user_id, operation, table_name, record_id, changes) VALUES (:ts, :uid, :op, :tn, :rid, :ch)"),
                    {
                        "ts": datetime.now(),  # Utiliser un objet datetime directement
                        "uid": user_id,
                        "op": "UPDATE",
                        "tn": "User",
                        "rid": user_id,
                        "ch": json.dumps({
                            "credits": {
                                "old": float(current_user_credits),
                                "new": float(new_credits)
                            }
                        })
                    }
                )
            except Exception as track_err:
                logger.warning(f"[{task_id}] Erreur lors du suivi du changement de crédits: {track_err}")
                
            db.session.commit()
            logger.info(f"[{task_id}] Crédits de l'utilisateur {user_id} mis à jour: {current_user_credits} -> {new_credits}")
    except Exception as db_update_err:
        logger.error(f"[{task_id}] Échec de la mise à jour des crédits pour user {user_id}: {db_update_err}", exc_info=True)
        db.session.rollback()
        db_update_error_msg = str(db_update_err)
    
    # Déterminer le statut final
    final_status = "SUCCESS"
    error_details = []
    
    if not final_json_saved:
        final_status = "FAILURE"
        error_details.append(f"Sauvegarde JSON échouée: {save_error_msg}")
    
    if db_update_error_msg:
        error_details.append(f"MAJ crédits échouée: {db_update_error_msg}")
    
    # Message de résultat
    message = f"Traitement OCR terminé. {competences_count} compétences extraites."
    if error_details:
        message += " Erreurs rencontrées: " + "; ".join(error_details)
    
    if competences_count == 0 and final_status == "SUCCESS":
        message = "Traitement OCR terminé. Aucune compétence extraite ou trouvée."
    
    logger.info(f"[{task_id}] Statut final déterminé: {final_status}")
    
    # Préparer les métadonnées du résultat final
    # Récupérer les informations importantes de la tâche principale
    pdf_source = original_info.get('pdf_source') or getattr(original_task_result, 'args', [None])[0] if hasattr(original_task_result, 'args') else None
    pdf_title = original_info.get('pdf_title') or getattr(original_task_result, 'args', [None, None])[1] if hasattr(original_task_result, 'args') else None
    
    final_result_meta = {
        'task_id': original_task_id,
        'callback_task_id': task_id,
        'final_status': final_status,
        'message': message,
        'json_output_path': json_output_path if final_json_saved else None,
        'competences_count': competences_count,
        'openai_cost': total_cost,
        'usage_details': total_usage,
        'db_update_error': db_update_error_msg,
        'save_error': save_error_msg,
        'progress': 100,
        'step': 'Agrégation Terminée',
        'base_filename': base_filename,
        # Ajouter les informations manquantes
        'pdf_source': pdf_source,
        'pdf_title': pdf_title,
        'ocr_markdown_path': original_info.get('ocr_markdown_path'),
        'download_path': original_info.get('download_path')
    }
    
    # Mise à jour de l'état de la tâche originale
    logger.info(f"[{task_id}] Tentative de mise à jour de l'état de la tâche originale {original_task_id} vers {final_status}")
    try:
        original_task_signature = signature('app.tasks.process_ocr_task', app=celery)
        original_task_result = original_task_signature.AsyncResult(original_task_id)
        original_task_result.backend.store_result(original_task_id, final_result_meta, 'SUCCESS')
        logger.info(f"[{task_id}] État de la tâche originale {original_task_id} mis à jour vers {final_status}.")
    except Exception as update_orig_err:
        logger.error(f"[{task_id}] Impossible de mettre à jour l'état de la tâche originale {original_task_id}: {update_orig_err}", exc_info=True)
    
    # Mise à jour de l'état de cette tâche
    self.update_state(state=final_status, meta=final_result_meta)
    
    return final_result_meta

###############################################################################
# Tâche Principale OCR (Refactorisée avec Callback)
###############################################################################
@shared_task(bind=True)
def process_ocr_task(self, pdf_source, pdf_title, user_id, openai_key_ignored):
    """
    Tâche principale pour l'OCR :
     - Vérifie utilisateur, configure chemins.
     - Télécharge/Prépare PDF.
     - Lance OCR (via API externe).
     - Lance Segmentation (via API OpenAI).
     - Lance un groupe de tâches extract_json_competence en parallèle.
     - LIE une tâche aggregate_ocr_results_task qui s'exécutera APRES le groupe.
     - Se termine (état PROGRESS), le résultat final sera défini par le callback.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Démarrage tâche principale process_ocr_task...")

    def update_progress(stage, message, progress, details=None):
        meta = {
            'step': stage,
            'message': message,
            'progress': progress,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title
        }
        if details:
            meta['details'] = details
        try:
            self.update_state(state='PROGRESS', meta=meta)
            logger.debug(f"[{task_id}] State updated to PROGRESS: {stage} - {progress}%")
        except Exception as update_err:
            logger.error(f"[{task_id}] Failed to update Celery state: {update_err}")
            
    update_progress("Initialisation", "Démarrage de la tâche...", 0)
    logger.info(f"[{task_id}] Traitement OCR pour: {pdf_title} ({pdf_source}) par user_id: {user_id}")
    openai_key = None
    user_credits_initial = None
    pdf_output_dir = None
    txt_output_dir = None
    base_filename_local = None
    download_path_local = None
    ocr_markdown_path_local = None
    competences_pages = []
    segmentation_usage_dict = None

    try:
        logger.info(f"[{task_id}] Vérification utilisateur et crédits...")
        try:
            user_data = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
            if not user_data:
                raise ValueError(f"Utilisateur {user_id} introuvable.")
            openai_key = user_data.openai_key
            user_credits_initial = user_data.credits
            if not openai_key:
                raise ValueError(f"Aucune clé OpenAI configurée pour l'utilisateur {user_id}.")
            if user_credits_initial is None or user_credits_initial <= 0:
                logger.warning(f"[{task_id}] Crédits initiaux insuffisants ou invalides ({user_credits_initial}) pour {user_id}.")
            logger.info(f"[{task_id}] Utilisateur {user_id} OK. Crédits initiaux: {user_credits_initial}. Clé API présente.")
        except Exception as db_err:
            logger.critical(f"[{task_id}] Erreur DB récupération utilisateur {user_id}: {db_err}", exc_info=True)
            raise RuntimeError(f"Erreur DB utilisateur: {db_err}")
            
        logger.info(f"[{task_id}] Configuration des chemins...")
        try:
            pdf_output_dir = current_app.config.get('PDF_OUTPUT_DIR', 'pdfs_downloaded')
            txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR', 'txt_outputs')
            if not txt_output_dir:
                raise ValueError("TXT_OUTPUT_DIR n'est pas configuré dans l'application Flask.")
            os.makedirs(pdf_output_dir, exist_ok=True)
            os.makedirs(txt_output_dir, exist_ok=True)
            logger.info(f"[{task_id}] Répertoires OK: PDF='{pdf_output_dir}', TXT='{txt_output_dir}'")
        except Exception as config_err:
            logger.critical(f"[{task_id}] Erreur config/création répertoires: {config_err}", exc_info=True)
            raise RuntimeError(f"Erreur configuration: {config_err}")
            
        update_progress("Détermination", "Étape 0/5 - Nom de fichier", 5)
        logger.info(f"[{task_id}] Étape 0: Détermination nom de fichier...")
        programme_code = extract_code_from_title(pdf_title)
        base_filename_local = determine_base_filename(programme_code, pdf_title)
        if not base_filename_local:
            raise ValueError(f"Impossible de déterminer nom de fichier base pour: {pdf_title}")
        logger.info(f"[{task_id}] Nom fichier base: {base_filename_local}")
        
        # Mettre à jour l'état avec le nom de fichier de base
        self.update_state(state='PROGRESS', meta={
            'step': 'Détermination',
            'message': "Nom fichier déterminé",
            'progress': 10,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local
        })
        
        update_progress("PDF", "Étape 1/5 - Préparation PDF", 15)
        logger.info(f"[{task_id}] Étape 1: Gestion PDF source...")
        if pdf_source.startswith('http://') or pdf_source.startswith('https://'):
            logger.info(f"[{task_id}] Téléchargement URL: {pdf_source}")
            download_path_local = web_utils.telecharger_pdf(pdf_source, pdf_output_dir)
            if not download_path_local or not os.path.exists(download_path_local):
                raise RuntimeError(f"Échec téléchargement ou chemin invalide: {pdf_source} -> {download_path_local}")
            logger.info(f"[{task_id}] PDF téléchargé: {download_path_local}")
        elif os.path.exists(pdf_source):
            target_filename = base_filename_local + ".pdf"
            download_path_local = os.path.join(pdf_output_dir, target_filename)
            if os.path.abspath(pdf_source) != os.path.abspath(download_path_local):
                import shutil
                shutil.copy2(pdf_source, download_path_local)
                logger.info(f"[{task_id}] Fichier local copié: {download_path_local}")
            else:
                logger.info(f"[{task_id}] Utilisation fichier local existant: {download_path_local}")
        else:
            raise FileNotFoundError(f"Source PDF invalide/non trouvée: {pdf_source}")
            
        # Mettre à jour l'état avec les chemins de fichiers
        self.update_state(state='PROGRESS', meta={
            'step': 'PDF',
            'message': "PDF prêt",
            'progress': 25,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local
        })
        
        update_progress("OCR", "Étape 2/5 - OCR en cours...", 30)
        logger.info(f"[{task_id}] Étape 2: Lancement OCR...")
        ocr_markdown_path_local = os.path.join(txt_output_dir, f"{base_filename_local}_ocr.md")
        ocr_input_source = pdf_source if pdf_source.startswith('http') else download_path_local
        logger.info(f"[{task_id}] Appel perform_ocr_and_save: Input='{ocr_input_source}', Output='{ocr_markdown_path_local}'")
        ocr_success = api_clients.perform_ocr_and_save(ocr_input_source, ocr_markdown_path_local)
        if not ocr_success:
            if not os.path.exists(ocr_markdown_path_local) or os.path.getsize(ocr_markdown_path_local) == 0:
                raise RuntimeError("Étape OCR échouée: Fichier Markdown non créé ou vide.")
            else:
                logger.warning(f"[{task_id}] perform_ocr_and_save retourné False mais fichier existe. Poursuite...")
        logger.info(f"[{task_id}] OCR Markdown généré: {ocr_markdown_path_local}")
        
        # Mettre à jour l'état avec le chemin OCR
        self.update_state(state='PROGRESS', meta={
            'step': 'OCR',
            'message': "OCR terminé",
            'progress': 40,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local,
            'ocr_markdown_path': ocr_markdown_path_local
        })
        
        update_progress("Segmentation", "Étape 3/5 - Segmentation...", 45)
        logger.info(f"[{task_id}] Étape 3: Segmentation compétences...")
        try:
            with open(ocr_markdown_path_local, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            if not markdown_content:
                raise ValueError(f"Fichier Markdown OCR vide: {ocr_markdown_path_local}")
            logger.info(f"[{task_id}] Lecture Markdown OK ({len(markdown_content)} chars).")
        except Exception as read_err:
            raise RuntimeError(f"Erreur lecture fichier OCR: {read_err}")
            
        try:
            logger.info(f"[{task_id}] Appel find_competences_pages...")
            segmentation_output = api_clients.find_competences_pages(markdown_content, openai_key)
            logger.debug(f"[{task_id}] Réponse brute de find_competences_pages: {segmentation_output}")
            
            if isinstance(segmentation_output, dict):
                competences_pages = segmentation_output.get("result", {}).get("competences", [])
                segmentation_usage = segmentation_output.get("usage")
                logger.debug(f"[{task_id}] Usage brut de segmentation: {segmentation_usage}, type: {type(segmentation_usage)}")
                
                # Initialiser la variable même si elle n'est pas définie par la suite
                segmentation_usage_dict = None
                
                if segmentation_usage and hasattr(segmentation_usage, 'input_tokens'):
                    logger.debug(f"[{task_id}] Usage a des attributs input_tokens: {getattr(segmentation_usage, 'input_tokens', 0)}")
                    segmentation_usage_dict = {
                        "prompt_tokens": getattr(segmentation_usage, 'input_tokens', 0),
                        "completion_tokens": getattr(segmentation_usage, 'output_tokens', 0),
                    }
                elif segmentation_usage and hasattr(segmentation_usage, 'prompt_tokens'):
                    logger.debug(f"[{task_id}] Usage a des attributs prompt_tokens: {getattr(segmentation_usage, 'prompt_tokens', 0)}")
                    segmentation_usage_dict = {
                        "prompt_tokens": getattr(segmentation_usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(segmentation_usage, 'completion_tokens', 0),
                    }
                elif isinstance(segmentation_usage, dict):
                    logger.debug(f"[{task_id}] Usage est un dict: {segmentation_usage}")
                    segmentation_usage_dict = segmentation_usage
                else:
                    logger.warning(f"[{task_id}] Format d'usage non reconnu: {segmentation_usage}")
                    # Créer un dictionnaire vide mais valide pour éviter les None
                    segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
                    
                logger.info(f"[{task_id}] Segmentation OK ({len(competences_pages)} compétences trouvées). Usage final: {segmentation_usage_dict}")
            else:
                logger.warning(f"[{task_id}] find_competences_pages retour inattendu: {type(segmentation_output)}")
                competences_pages = []
                segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
        except Exception as seg_err:
            logger.error(f"[{task_id}] Erreur find_competences_pages: {seg_err}", exc_info=True)
            competences_pages = []
            segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
            
        # Mettre à jour l'état avec les résultats de segmentation
        self.update_state(state='PROGRESS', meta={
            'step': 'Segmentation',
            'message': "Segmentation terminée",
            'progress': 50,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local,
            'ocr_markdown_path': ocr_markdown_path_local,
            'competences_count': len(competences_pages)
        })
        
        json_output_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences.json")
        model_section = current_app.config.get('OPENAI_MODEL_SECTION')
        model_extraction = current_app.config.get('OPENAI_MODEL_EXTRACTION')
        
        if competences_pages:
            total_competences = len(competences_pages)
            update_progress("Lancement Extraction", f"Étape 4/5 - Lancement extraction pour {total_competences} compétences...", 55)
            logger.info(f"[{task_id}] Étape 4: Lancement groupe pour {total_competences} compétences...")
            
            extraction_tasks_signatures = [
                extract_json_competence.s(
                    comp, download_path_local, txt_output_dir, base_filename_local, openai_key
                )
                for comp in competences_pages if comp.get('code') and comp.get('page_debut') is not None
            ]
            
            if not extraction_tasks_signatures:
                logger.warning(f"[{task_id}] Aucune compétence valide à traiter après filtrage.")
                final_status_internal = "SUCCESS"
                message = "Traitement terminé. Aucune compétence valide à extraire."
                final_meta = {
                    'task_id': task_id,
                    'final_status': final_status_internal,
                    'message': message,
                    'competences_count': 0,
                    'progress': 100,
                    'step': 'Terminé (Aucune Compétence Valide)',
                    'pdf_source': pdf_source,
                    'pdf_title': pdf_title,
                    'base_filename': base_filename_local,
                    'download_path': download_path_local,
                    'ocr_markdown_path': ocr_markdown_path_local
                }
                self.update_state(state="SUCCESS", meta=final_meta)
                logger.info(f"[{task_id}] Mise à jour état final: {final_status_internal} (Aucune compétence valide)")
                return final_meta

            # Préparation du callback avec les paramètres requis
            callback_task_signature = aggregate_ocr_results_task.s(
                original_task_id=task_id,
                json_output_path=json_output_path,
                base_filename=base_filename_local,
                user_id=user_id,
                user_credits_initial=user_credits_initial,
                model_section=model_section,
                model_extraction=model_extraction,
                segmentation_usage_dict=segmentation_usage_dict
            )
            
            # Lancer le chord de manière asynchrone
            header = group(extraction_tasks_signatures)
            chord_result = (header | callback_task_signature).apply_async()

            # Mettre à jour l'état final avec toutes les informations importantes
            final_meta = {
                'task_id': chord_result.id,
                'message': "Le workflow a été lancé. Veuillez consulter le statut ultérieurement.",
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local,
                'ocr_markdown_path': ocr_markdown_path_local,
                'competences_count_initial': len(competences_pages),
                'json_output_path': json_output_path,
                'step': 'Traitement Asynchrone',
                'progress': 60
            }
            
            update_progress("Traitement Asynchrone", "Lancement des tâches d'extraction en arrière-plan...", 60)

            # Retourner l'ID du chord et toutes les informations importantes
            return final_meta

        else:
            update_progress("Terminé", "Aucune compétence trouvée", 100)
            logger.warning(f"[{task_id}] Aucune compétence trouvée lors de la segmentation. Traitement terminé.")
            final_status_internal = "SUCCESS"
            message = "Traitement OCR terminé. Aucune compétence trouvée ou extraite."
            final_meta = {
                'task_id': task_id,
                'final_status': final_status_internal,
                'message': message,
                'competences_count': 0,
                'progress': 100,
                'step': 'Terminé (Aucune Compétence)',
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local,
                'ocr_markdown_path': ocr_markdown_path_local
            }
            self.update_state(state="SUCCESS", meta=final_meta)
            logger.info(f"[{task_id}] Mise à jour état final: {final_status_internal} (Aucune compétence)")
            return final_meta

    except Exception as e:
        logger.critical(f"[{task_id}] Erreur majeure inattendue dans process_ocr_task (avant lancement callback): {e}", exc_info=True)
        final_status_internal = "FAILURE"
        error_message = f"Erreur inattendue (avant callback): {str(e)}"
        try:
            db.session.rollback()
            logger.info(f"[{task_id}] Rollback BDD effectué suite à l'erreur.")
        except Exception as rb_err:
            logger.error(f"[{task_id}] Erreur lors du rollback BDD: {rb_err}", exc_info=True)
        final_meta = {
            'task_id': task_id,
            'final_status': final_status_internal,
            'error': error_message,
            'message': error_message,
            'progress': 100,
            'step': 'Erreur Initiale',
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local if base_filename_local else None,
            'download_path': download_path_local if download_path_local else None,
            'ocr_markdown_path': ocr_markdown_path_local if ocr_markdown_path_local else None
        }
        logger.info(f"[{task_id}] Tentative de mise à jour finale de l'état Celery vers '{final_status_internal}' (erreur pré-callback)")
        try:
            self.update_state(state="SUCCESS", meta=final_meta)
            logger.info(f"[{task_id}] Mise à jour finale de l'état Celery vers 'SUCCESS' réussie.")
        except Exception as final_update_err:
            logger.error(f"[{task_id}] ÉCHEC CRITIQUE: Impossible de mettre à jour l'état final Celery: {final_update_err}", exc_info=True)
        return final_meta