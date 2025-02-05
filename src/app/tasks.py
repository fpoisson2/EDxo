# app/tasks.py

import json
import time
import logging
from sqlalchemy import text
from celery_app import celery  # Your Celery instance (configured with your Flask app)
from extensions import db    # Your SQLAlchemy instance
# Import your models – adjust these imports as needed:
from app.models import (
    PlanCadre, GlobalGenerationSettings, Competence, ElementCompetence,
    ElementCompetenceParCours, CoursCorequis, Cours, CoursPrealable,
    PlanCadreSavoirEtre, PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires, PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation, User
)
# Import any helper functions used in your logic
from utils.utils import replace_tags_jinja2, get_plan_cadre_data

# Import your OpenAI client (adjust this import according to your library)
from openai import OpenAI

from pydantic import BaseModel
from typing import List, Optional

from utils.openai_pricing import calculate_call_cost

###############################################################################
# Schemas Pydantic pour IA
###############################################################################
class AIField(BaseModel):
    """Represents older PlanCadre fields (e.g. place_intro, objectif_terminal)."""
    field_name: Optional[str] = None
    content: Optional[str] = None

class AIContentDetail(BaseModel):
    texte: Optional[str] = None
    description: Optional[str] = None

class AIFieldWithDescription(BaseModel):
    field_name: Optional[str] = None
    content: Optional[List[AIContentDetail]] = None  # for structured lists

class AISavoirFaire(BaseModel):
    texte: Optional[str] = None
    cible: Optional[str] = None
    seuil_reussite: Optional[str] = None

class AICapacite(BaseModel):
    """
    A single 'capacité' with optional sub-lists for:
      - savoirs_necessaires
      - savoirs_faire
      - moyens_evaluation
    """
    capacite: Optional[str] = None
    description_capacite: Optional[str] = None
    ponderation_min: Optional[int] = None
    ponderation_max: Optional[int] = None

    savoirs_necessaires: Optional[List[str]] = None
    savoirs_faire: Optional[List[AISavoirFaire]] = None
    moyens_evaluation: Optional[List[str]] = None

class PlanCadreAIResponse(BaseModel):
    """
    The GPT response:
      - fields: (list of AIField)
      - fields_with_description: (list of AIFieldWithDescription)
      - savoir_etre: (list of strings)
      - capacites: (list of AICapacite)
    """
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
      - Calls the OpenAI API twice to generate content.
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

        # Mise à jour de l'état pour notifier le client que la génération est en cours
        self.update_state(
            state='PROGRESS',
            meta={'message': f"Génération automatique du plan-cadre du cours {cours_nom} en cours"}
        )
        
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
        
        # Initialize lists for AI/non-AI processing
        ai_fields = []
        ai_fields_with_description = []
        non_ai_updates_plan_cadre = []
        non_ai_inserts_other_table = []
        ai_savoir_etre = None
        ai_capacites_prompt = []
        
        def replace_jinja(text_):
            return replace_tags_jinja2(text_, plan_cadre_data)
        
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
                        .join(ElementCompetenceParCours, ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
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
                        .join(ElementCompetenceParCours, ElementCompetenceParCours.element_competence_id == ElementCompetence.id)
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
                # Other sections are ignored
        
        # Apply non-AI updates on the plan
        for col_name, val in non_ai_updates_plan_cadre:
            setattr(plan, col_name, val)
        
        # Execute non-AI inserts into other tables
        for table_name, val in non_ai_inserts_other_table:
            db.session.execute(
                text(f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (:pcid, :val)"),
                {"pcid": plan.id, "val": val}
            )
        
        db.session.commit()
        
        # If no AI generation is required, return early.
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            return {"status": "success", "message": "Aucune génération IA requise (tous champs sont en mode non-AI)."}
        
        # Prepare the JSON schema and structured prompt for the AI
        schema_json = json.dumps(PlanCadreAIResponse.schema(), indent=4, ensure_ascii=False)
        
        role_message = (
            f"Tu es un rédacteur de contenu pour un plan-cadre de cours '{cours_nom}', "
            f"session {cours_session}. Retourne un JSON valide correspondant à PlanCadreAIResponse."
        )
        
        structured_request = {
            "instruction": (
                f"Tu es un rédacteur pour un plan-cadre de cours '{cours_nom}', "
                f"session {cours_session}. Informations supplémentaires: {additional_info}\n\n"
                "Voici le schéma JSON auquel ta réponse doit strictement adhérer :\n\n"
                f"{schema_json}\n\n"
                "Utilise un langage neutre (par exemple, 'étudiant' => 'personne étudiante').\n\n"
                "Voici différents prompts:\n"
                f"- fields: {ai_fields}\n\n"
                f"- fields_with_description: {ai_fields_with_description}\n\n"
                f"- savoir_etre: {ai_savoir_etre}\n\n"
                f"- capacites: {ai_capacites_prompt}\n\n"
            )
        }
        
        # Initialize the OpenAI client with the user's key
        client = OpenAI(api_key=openai_key)
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        
        # First OpenAI API call
        try:
            o1_response = client.beta.chat.completions.parse(
                model=ai_model,
                messages=[{"role": "user", "content": json.dumps(structured_request)}]
            )
        except Exception as e:
            logging.error(f"OpenAI error (premier appel): {e}")
            return {"status": "error", "message": f"Erreur API OpenAI (premier appel): {str(e)}"}
        
        if hasattr(o1_response, 'usage'):
            total_prompt_tokens += o1_response.usage.prompt_tokens
            total_completion_tokens += o1_response.usage.completion_tokens
        
        o1_response_content = o1_response.choices[0].message.content if o1_response.choices else ""
        
        # Second OpenAI API call to format the response
        try:
            completion = client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Connaissant les données suivantes, formatte-les selon "
                            f"le response_format demandé: {o1_response_content}"
                        )
                    }
                ],
                response_format=PlanCadreAIResponse,
            )
        except Exception as e:
            logging.error(f"OpenAI error (second appel): {e}")
            return {"status": "error", "message": f"Erreur API OpenAI (second appel): {str(e)}"}
        
        if hasattr(completion, 'usage'):
            total_prompt_tokens += completion.usage.prompt_tokens
            total_completion_tokens += completion.usage.completion_tokens
        
        # Calculate the cost and update user credits
        try:
            usage_1_prompt = o1_response.usage.prompt_tokens if hasattr(o1_response, 'usage') else 0
            usage_1_completion = o1_response.usage.completion_tokens if hasattr(o1_response, 'usage') else 0
            cost_first_call = calculate_call_cost(usage_1_prompt, usage_1_completion, ai_model)
        
            usage_2_prompt = completion.usage.prompt_tokens if hasattr(completion, 'usage') else 0
            usage_2_completion = completion.usage.completion_tokens if hasattr(completion, 'usage') else 0
            cost_second_call = calculate_call_cost(usage_2_prompt, usage_2_completion, "gpt-4o")
        
            total_cost = cost_first_call + cost_second_call
        
            logging.info(f"Premier appel ({ai_model}): {cost_first_call:.6f}$ ({usage_1_prompt} prompt, {usage_1_completion} completion)")
            logging.info(f"Second appel (gpt-4o): {cost_second_call:.6f}$ ({usage_2_prompt} prompt, {usage_2_completion} completion)")
            logging.info(f"Coût total: {total_cost:.6f}$")
        
            new_credits = user_credits - total_cost
            if new_credits < 0:
                raise ValueError("Crédits insuffisants pour effectuer l'opération")
        
            db.session.execute(
                text("UPDATE User SET credits = :credits WHERE id = :uid"),
                {"credits": new_credits, "uid": user_id}
            )
            db.session.commit()
        
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
        
        # Process the AI-generated content
        parsed_data: PlanCadreAIResponse = completion.choices[0].message.parsed
        
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
                    {
                        "pid": plan.id,
                        "txt": texte_comp,
                        "desc": desc_comp
                    }
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
        return result
    
    except Exception as e:
        db.session.rollback()
        logging.error("Unexpected error: %s", e, exc_info=True)
        return {"status": "error", "message": f"Erreur lors de la génération du contenu: {str(e)}"}
