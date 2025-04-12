# app/tasks.py
import os


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
    PlanCadreCapaciteMoyensEvaluation, User
)
from celery_app import celery  # Your Celery instance (configured with your Flask app)
from extensions import db  # Your SQLAlchemy instance
from utils.openai_pricing import calculate_call_cost
# Import any helper functions used in your logic
from utils.utils import replace_tags_jinja2, get_plan_cadre_data

from ocr_processing import api_clients, pdf_tools, web_utils

from config.constants import *


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


@celery.task(bind=True)
def process_ocr_task(self, pdf_source, pdf_title="Unknown PDF"):
    """
    Celery task to download (optional), OCR, and extract skills from a PDF.
    Updates task state for progress tracking.
    """
    task_id = self.request.id
    logging.info(f"Celery Task {task_id}: Starting OCR process for '{pdf_title}' ({pdf_source})")

    # --- Define base directory for outputs related to this task ---
    # You might want a more robust way to handle temporary files/folders
    # For now, using a subfolder in TXT_FOLDER based on task_id
    # Ensure TXT_FOLDER is defined in your config or adapt this
    base_output_dir = "txt_outputs"
    os.makedirs(base_output_dir, exist_ok=True)

    # --- Result dictionary (similar to main_logic.py) ---
    results = {
        "task_id": task_id,
        "pdf_title": pdf_title,
        "pdf_source": pdf_source,
        "status": "STARTED",
        "download_path": None,
        "ocr_markdown_path": None,
        "section_info": None,
        "section_pdf_path": None,
        "txt_output_path": None,
        "json_output_path": None,
        "competences_count": 0,
        "final_status": "In Progress",
        "error": None
    }

    try:
        # === ADAPTED WORKFLOW FROM main_logic.process_selected_pdf ===

        # --- Step 1: Get the PDF file path ---
        # If pdf_source is a URL, download it. If it's already a path, use it.
        pdf_original_path = None
        if pdf_source.startswith('http://') or pdf_source.startswith('https://'):
            step_name = "download"
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Downloading: {pdf_title}..."})
            # Ensure DOWNLOAD_FOLDER is configured
            download_folder = "pdfs"
            pdf_original_path = web_utils.telecharger_pdf(pdf_source, download_folder) # Assumes web_utils is imported if needed
            if not pdf_original_path:
                raise ValueError(f"Failed to download PDF from {pdf_source}")
            results["download_path"] = pdf_original_path
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Downloaded: {os.path.basename(pdf_original_path)}"})
        else:
            # Assume pdf_source is already a local file path
            if os.path.exists(pdf_source):
                pdf_original_path = pdf_source
                results["download_path"] = pdf_original_path # Record the source path
                logging.info(f"Task {task_id}: Using existing file: {pdf_original_path}")
            else:
                 raise FileNotFoundError(f"Input PDF path not found: {pdf_source}")

        # Get base name for output files
        base_name = os.path.basename(pdf_original_path)
        base_name_no_ext = os.path.splitext(base_name)[0]

        # --- Step 2: OCR ---
        step_name = "ocr"
        self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "Starting OCR..."})
        markdown_filename = f"{base_name_no_ext}_ocr.md"
        markdown_path = os.path.join(base_output_dir, markdown_filename) # Save in task-specific dir
        # Use the original PDF URL if available for OCR, otherwise the path
        ocr_input_source = pdf_source if pdf_source.startswith('http') else pdf_original_path
        markdown_ok = api_clients.perform_ocr_and_save(ocr_input_source, markdown_path)
        page_info = None
        markdown_full_content = None

        if markdown_ok:
            results["ocr_markdown_path"] = markdown_path
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"OCR complete: {markdown_filename}"})
            try:
                with open(markdown_path, "rt", encoding="utf-8") as f:
                    markdown_full_content = f.read()

                # --- Step 3: Section Find ---
                step_name = "section_find"
                self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "Identifying section (OpenAI)..."})
                page_info = api_clients.find_section_with_openai(markdown_full_content) # Can return None
                results["section_info"] = page_info
                if page_info and page_info.get("page_debut"):
                    self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Section identified: Pages {page_info.get('page_debut')}-{page_info.get('page_fin')}."})
                else:
                    self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "Specific section not identified."})
            except Exception as md_err:
                logging.error(f"Task {task_id}: Error reading Markdown or finding section: {md_err}", exc_info=True)
                self.update_state(state='PROGRESS', meta={'step': 'section_find', 'message': f"Warning: Error during section find: {md_err}"})
        else:
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "OCR failed or skipped. Proceeding without section identification."})


        # --- Step 4: Section Extract ---
        step_name = "section_extract"
        pdf_to_convert = pdf_original_path
        section_pdf_path = None
        if page_info and page_info.get("page_debut") and page_info.get("page_fin"):
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Extracting PDF section (pages {page_info['page_debut']}-{page_info['page_fin']})..."})
            section_pdf_filename = f"{base_name_no_ext}_section.pdf"
            section_pdf_path = os.path.join(base_output_dir, section_pdf_filename) # Save in task-specific dir
            section_ok = pdf_tools.extract_pdf_section(
                pdf_original_path, section_pdf_path,
                page_info["page_debut"], page_info["page_fin"]
            )
            if section_ok:
                pdf_to_convert = section_pdf_path
                results["section_pdf_path"] = section_pdf_path
                self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Section PDF extracted: {section_pdf_filename}"})
            else:
                results["section_pdf_path"] = None
                self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "Warning: Failed to extract section. Using full PDF."})
        # (No message needed if section wasn't identified in the first place)


        # --- Step 5: Text Convert ---
        step_name = "text_convert"
        pdf_conv_basename = os.path.basename(pdf_to_convert)
        self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Converting '{pdf_conv_basename}' to text..."})
        txt_output_filename = f"{base_name_no_ext}.txt"
        txt_output_path = os.path.join(base_output_dir, txt_output_filename) # Save in task-specific dir
        text_content = pdf_tools.convert_pdf_to_txt(pdf_to_convert, txt_output_path)

        if not text_content:
             raise ValueError(f"Text conversion failed for {pdf_conv_basename}")

        results["txt_output_path"] = txt_output_path
        self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Text conversion successful: {txt_output_filename}"})


        # --- Step 6: Skill Extract ---
        step_name = "skill_extract"
        json_output_filename = f"{base_name_no_ext}_competences.json"
        json_output_path = os.path.join(base_output_dir, json_output_filename) # Save in task-specific dir
        self.update_state(state='PROGRESS', meta={'step': step_name, 'message': "Extracting competences (OpenAI stream)..."})

        # Define a simple callback for the stream chunks (optional, but good for finer progress)
        def stream_callback(payload):
             if payload.get("type") == "delta" and payload.get("data"):
                # Could potentially update state more frequently here, but might be too much.
                # For now, just log it if needed.
                # logging.debug(f"Task {task_id}: Stream delta received.")
                pass
             elif payload.get("type") == "error":
                 # Log errors reported during the stream
                 logging.error(f"Task {task_id}: Error during skill extraction stream: {payload.get('message')}")
                 # Maybe update state with a warning?
                 self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Warning during extraction: {payload.get('message')}"})


        # This call might raise SkillExtractionError
        competences_json_string = api_clients.extraire_competences_depuis_txt(
            text_content,
            json_output_path,
            callback=stream_callback # Pass the simple callback
        )

        results["json_output_path"] = json_output_path
        try:
            # Validate and count results
            competences_data = json.loads(competences_json_string)
            nb_competences = len(competences_data.get('competences', []))
            results["competences_count"] = nb_competences
            results["final_status"] = "SUCCESS"
            self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Extraction successful. Found {nb_competences} competences. Saved: {json_output_filename}"})
        except json.JSONDecodeError as json_err:
             results["final_status"] = "COMPLETED_WITH_INVALID_JSON"
             results["error"] = f"Final JSON parsing failed: {json_err}"
             logging.error(f"Task {task_id}: {results['error']}")
             self.update_state(state='PROGRESS', meta={'step': step_name, 'message': f"Warning: Extraction completed but final JSON is invalid: {json_err}"})


        # === End of Adapted Workflow ===

        logging.info(f"Task {task_id}: Process completed. Final status: {results['final_status']}")
        # Return the results dictionary upon success or partial success
        return results

    except api_clients.SkillExtractionError as skill_e:
         # Handle specific skill extraction failures
         error_msg = f"Critical failure during competence extraction: {skill_e}"
         logging.error(f"Task {task_id}: {error_msg}", exc_info=True)
         results["final_status"] = "FAILURE"
         results["error"] = error_msg
         self.update_state(state='FAILURE', meta=results)
         return results # Return results even on failure

    except Exception as e:
        # Handle any other unexpected errors
        error_msg = f"General critical error during OCR processing: {e}"
        logging.critical(f"Task {task_id}: {error_msg}", exc_info=True)
        results["final_status"] = "FAILURE"
        results["error"] = error_msg
        # Update Celery state to FAILURE
        self.update_state(state='FAILURE', meta=results)
        # Return the results dictionary containing the error
        return results