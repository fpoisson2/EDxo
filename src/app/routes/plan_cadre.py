# plan_de_cours.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, jsonify
from flask_login import login_required, current_user
from app.forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    MultiCheckboxField,
    PlanCadreForm,
    SavoirEtreForm,
    CompetenceDeveloppeeForm,
    ObjetCibleForm,
    CoursRelieForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm,
    GenerationSettingForm
)
from utils.decorator import roles_required, role_required
import json
import logging
import traceback

from pydantic import BaseModel
from typing import List, Optional

from bs4 import BeautifulSoup
import markdown

from docxtpl import DocxTemplate
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash

# Import SQLAlchemy DB and models
from app.models import (
    db,
    User,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    Cours,
    CoursPrealable,
    CoursCorequis,
    GlobalGenerationSettings,
    Competence,
    ElementCompetence,
    ElementCompetenceParCours
)

from openai import OpenAI
from openai import OpenAIError

from sqlalchemy import text

from utils.utils import (
    parse_html_to_list,
    parse_html_to_nested_list,
    get_plan_cadre_data,
    replace_tags_jinja2,
    process_ai_prompt,
    generate_docx_with_template,
    # Note: remove if no longer needed: get_db_connection
)

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

###############################################################################
# Configuration Logging
###############################################################################
logging.basicConfig(
    level=logging.ERROR,
    filename='app_errors.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

###############################################################################
# Blueprint
###############################################################################
plan_cadre_bp = Blueprint('plan_cadre', __name__, url_prefix='/plan_cadre')

MODEL_PRICING = {
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4o-mini": {"input": 0.150 / 1_000_000, "output": 0.600 / 1_000_000},
    "o1-preview": {"input": 15.00 / 1_000_000, "output": 60.00 / 1_000_000},
    "o1-mini": {"input": 3.00 / 1_000_000, "output": 12.00 / 1_000_000},
}

def calculate_call_cost(usage_prompt, usage_completion, model):
    """
    Calcule le coût d'un appel API en fonction du nombre de tokens et du modèle.
    """
    if model not in MODEL_PRICING:
        raise ValueError(f"Modèle {model} non trouvé dans la grille tarifaire")

    pricing = MODEL_PRICING[model]

    cost_input = usage_prompt * pricing["input"]
    cost_output = usage_completion * pricing["output"]
    return cost_input + cost_output

@plan_cadre_bp.route('/<int:plan_id>/generate_content', methods=['POST'])
@roles_required('admin', 'coordo')
def generate_plan_cadre_content(plan_id):
    """
    Gère la génération du contenu d’un plan-cadre via GPT.
    Récupère toutes les sections (IDs 43 à 63) depuis GlobalGenerationSettings, 
    applique ou non l’IA selon 'use_ai', et insère dans les tables adéquates.
    Permet aussi de calculer le coût des appels OpenAI et de le déduire du crédit 
    utilisateur.
    """
    # Remplacez cette importation/utilisation par ce qui convient dans votre code
    # (par ex.: from .forms import GenerateContentForm, etc.)
    form = GenerateContentForm()
    
    # Récupérer le plan-cadre via SQLAlchemy
    plan = PlanCadre.query.get(plan_id)
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=0, plan_id=plan_id))

    user_id = current_user.id
    # Récupérer l'utilisateur (et juste les champs nécessaires) via SQLAlchemy
    user = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
    if not user:
        flash('Utilisateur introuvable.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    openai_key = user.openai_key
    user_credits = user.credits  # Le nombre de crédits restants

    if not openai_key:
        flash('Aucune clé OpenAI configurée dans votre profil.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    # Vérification basique : l'utilisateur doit avoir > 0 crédits pour tenter la requête
    if user_credits <= 0:
        flash('Vous n’avez plus de crédits pour effectuer un appel OpenAI.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    if not form.validate_on_submit():
        flash('Erreur de validation du formulaire.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

    try:
        additional_info = form.additional_info.data
        ai_model = form.ai_model.data  # ex : "gpt-4o", "gpt-4o-mini", "o1-preview", "o1-mini", etc.

        # Sauvegarder les données supplémentaires dans la base de données
        plan.additional_info = additional_info
        plan.ai_model = ai_model
        db.session.commit()

        # ----------------------------------------------------------
        # 1) Préparation des data & des settings
        # ----------------------------------------------------------
        cours_nom = plan.cours.nom if plan.cours else "Non défini"
        cours_session = plan.cours.session if (plan.cours and plan.cours.session) else "Non défini"

        # Récupérer les paramètres 43 → 63 depuis GlobalGenerationSettings
        # (Ici, on récupère toutes les entrées ; modifiez si besoin de filtres.)
        parametres_generation = (
            db.session.query(GlobalGenerationSettings.section,
                             GlobalGenerationSettings.use_ai,
                             GlobalGenerationSettings.text_content)
            .all()
        )

        parametres_dict = {
            row.section: {
                'use_ai': row.use_ai,
                'text_content': row.text_content
            }
            for row in parametres_generation
        }

        plan_cadre_data = get_plan_cadre_data(plan.cours_id)

        # 1A) Mapping : quel champ va où ?
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

        # ----------------------------------------------------------
        # 1B) Parcours des sections pour déterminer "AI vs direct"
        # ----------------------------------------------------------
        ai_fields = []
        ai_fields_with_description = []
        non_ai_updates_plan_cadre = []
        non_ai_inserts_other_table = []
        ai_savoir_etre = None
        ai_capacites_prompt = []

        def replace_jinja(text_):
            return replace_tags_jinja2(text_, plan_cadre_data)

        # Parcours des sections
        for section_name, conf_data in parametres_dict.items():
            raw_text = str(conf_data.get('text_content', "") or "")
            replaced_text = replace_jinja(raw_text)
            is_ai = (conf_data.get('use_ai', 0) == 1)

            if section_name in field_to_plan_cadre_column:
                # Mise à jour directe dans PlanCadre ?
                col_name = field_to_plan_cadre_column[section_name]
                if is_ai:
                    ai_fields.append({"field_name": section_name, "prompt": replaced_text})
                else:
                    non_ai_updates_plan_cadre.append((col_name, replaced_text))

            elif section_name in field_to_table_insert:
                # Mise à jour dans une autre table ?
                table_name = field_to_table_insert[section_name]

                # Différents cas pour enrichir le prompt si besoin
                if section_name == "Objets cibles" and is_ai:
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des compétences développées" and is_ai:
                    # Récupérer les compétences "développées" pour le cours
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
                    # Récupérer les compétences "certifiées"
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
                    # Récupérer les cours corequis
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
                    # Récupérer les cours pour lesquels ce cours est un prérequis
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

                # Si pas d'IA :
                if not is_ai:
                    non_ai_inserts_other_table.append((table_name, replaced_text))

            else:
                # Champs spéciaux
                target_sections = [
                    'Capacité et pondération',
                    "Savoirs nécessaires d'une capacité",
                    "Savoirs faire d'une capacité",
                    "Moyen d'évaluation d'une capacité"
                ]
                # Savoir-être
                if section_name == 'Savoir-être':
                    if is_ai:
                        ai_savoir_etre = replaced_text
                    else:
                        lines = [l.strip() for l in replaced_text.split("\n") if l.strip()]
                        for line in lines:
                            se_obj = PlanCadreSavoirEtre(plan_cadre_id=plan.id, texte=line)
                            db.session.add(se_obj)

                # Capacités
                elif section_name in target_sections:
                    if is_ai:
                        section_formatted = f"### {section_name}\n{replaced_text}"
                        ai_capacites_prompt.append(section_formatted)
                    else:
                        # Pas d'IA => insertion directe ? (A adapter si nécessaire)
                        pass
                else:
                    # Section inconnue => on ignore ou on gère autrement
                    pass

        # ----------------------------------------------------------
        # 1C) Exécuter les updates/inserts "non-AI" (direct)
        # ----------------------------------------------------------
        # Mises à jour directes PlanCadre
        for col_name, val in non_ai_updates_plan_cadre:
            setattr(plan, col_name, val)

        # Insertion dans tables associées
        for table_name, val in non_ai_inserts_other_table:
            # On utilise un exécutable brut pour coller au "INSERT INTO" (pas d'ORM direct).
            db.session.execute(
                text(f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (:pcid, :val)"),
                {"pcid": plan.id, "val": val}
            )

        db.session.commit()

        # ----------------------------------------------------------
        # 1D) Vérifier si on doit appeler GPT
        # ----------------------------------------------------------
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            flash('Aucune génération IA requise (tous champs sont en mode non-AI).', 'success')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        # ----------------------------------------------------------
        # 2) Construire le prompt + Appeler GPT
        # ----------------------------------------------------------
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

        client = OpenAI(api_key=openai_key)

        total_prompt_tokens = 0
        total_completion_tokens = 0

        # ---- Premier appel : on envoie la requête user => model=ai_model
        try:
            o1_response = client.beta.chat.completions.parse(
                model=ai_model,
                messages=[{"role": "user", "content": json.dumps(structured_request)}]
            )
        except Exception as e:
            logging.error(f"OpenAI error (premier appel): {e}")
            flash(f"Erreur API OpenAI: {str(e)}", 'danger')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        # Récupérer la consommation (tokens) du premier appel
        if hasattr(o1_response, 'usage'):
            total_prompt_tokens += o1_response.usage.prompt_tokens
            total_completion_tokens += o1_response.usage.completion_tokens

        # ---- Second appel : on envoie la réponse du premier comme prompt,
        #      puis on parse directement au format PlanCadreAIResponse
        o1_response_content = o1_response.choices[0].message.content if o1_response.choices else ""

        try:
            completion = client.beta.chat.completions.parse(
                model="gpt-4o",  # Fixé à "gpt-4o" (selon votre code)
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
            flash(f"Erreur API OpenAI: {str(e)}", 'danger')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        # Récupérer la consommation (tokens) du second appel
        if hasattr(completion, 'usage'):
            total_prompt_tokens += completion.usage.prompt_tokens
            total_completion_tokens += completion.usage.completion_tokens

        # ----------------------------------------------------------
        # 2B) Calculer le coût total
        # ----------------------------------------------------------
        try:
            usage_1_prompt = o1_response.usage.prompt_tokens if hasattr(o1_response, 'usage') else 0
            usage_1_completion = o1_response.usage.completion_tokens if hasattr(o1_response, 'usage') else 0
            cost_first_call = calculate_call_cost(usage_1_prompt, usage_1_completion, ai_model)

            usage_2_prompt = completion.usage.prompt_tokens if hasattr(completion, 'usage') else 0
            usage_2_completion = completion.usage.completion_tokens if hasattr(completion, 'usage') else 0
            cost_second_call = calculate_call_cost(usage_2_prompt, usage_2_completion, "gpt-4o")

            total_cost = cost_first_call + cost_second_call

            print(f"Premier appel ({ai_model}): {cost_first_call:.6f}$ "
                  f"({usage_1_prompt} prompt, {usage_1_completion} completion)")
            print(f"Second appel (gpt-4o): {cost_second_call:.6f}$ "
                  f"({usage_2_prompt} prompt, {usage_2_completion} completion)")
            print(f"Coût total: {total_cost:.6f}$")

            new_credits = user_credits - total_cost
            if new_credits < 0:
                raise ValueError("Crédits insuffisants pour effectuer l'opération")

            db.session.execute(
                text("UPDATE User SET credits = :credits WHERE id = :uid"),
                {"credits": new_credits, "uid": user_id}
            )
            db.session.commit()

        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

        # ----------------------------------------------------------
        # 3) Parse & insertion en base du retour GPT
        # ----------------------------------------------------------
        parsed_data: PlanCadreAIResponse = completion.choices[0].message.parsed

        def clean_text(val):
            return val.strip().strip('"').strip("'") if val else ""

        # 3A) fields -> (PlanCadre ou autres tables)
        for fobj in (parsed_data.fields or []):
            fname = fobj.field_name
            fcontent = clean_text(fobj.content)
            if fname in field_to_plan_cadre_column:
                col = field_to_plan_cadre_column[fname]
                setattr(plan, col, fcontent)

        # 3A-bis) fields_with_description -> insertion dans la table correspondante
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
                # Équivalent "INSERT OR REPLACE" en brut:
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

        # 3B) savoir_etre -> PlanCadreSavoirEtre
        if parsed_data.savoir_etre:
            for se_item in parsed_data.savoir_etre:
                se_obj = PlanCadreSavoirEtre(
                    plan_cadre_id=plan.id,
                    texte=clean_text(se_item)
                )
                db.session.add(se_obj)

        # 3C) capacites -> PlanCadreCapacites + sous-tables
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
                db.session.flush()  # Permet de récupérer new_cap.id avant de continuer

                # Savoirs nécessaires
                if cap.savoirs_necessaires:
                    for sn in cap.savoirs_necessaires:
                        sn_obj = PlanCadreCapaciteSavoirsNecessaires(
                            capacite_id=new_cap.id,
                            texte=clean_text(sn)
                        )
                        db.session.add(sn_obj)

                # Savoirs-faire
                if cap.savoirs_faire:
                    for sf in cap.savoirs_faire:
                        sf_obj = PlanCadreCapaciteSavoirsFaire(
                            capacite_id=new_cap.id,
                            texte=clean_text(sf.texte),
                            cible=clean_text(sf.cible),
                            seuil_reussite=clean_text(sf.seuil_reussite)
                        )
                        db.session.add(sf_obj)

                # Moyens d'évaluation
                if cap.moyens_evaluation:
                    for me in cap.moyens_evaluation:
                        me_obj = PlanCadreCapaciteMoyensEvaluation(
                            capacite_id=new_cap.id,
                            texte=clean_text(me)
                        )
                        db.session.add(me_obj)

        db.session.commit()

        flash(f'Contenu généré automatiquement avec succès! Coût total: {round(total_cost, 4)} crédits.', 'success')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))

    except Exception as e:
        db.session.rollback()  # Annuler la transaction en cas d'erreur
        logging.error(f"Unexpected error: {e}")
        flash(f'Erreur lors de la génération du contenu: {e}', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan.cours_id, plan_id=plan_id))


###############################################################################
# Exporter un plan-cadre en DOCX
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/export', methods=['GET'])
@login_required
def export_plan_cadre(plan_id):
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé', 'danger')
        return redirect(url_for('main.index'))

    docx_file = generate_docx_with_template(plan_id)
    if not docx_file:
        flash('Erreur lors de la génération du document', 'danger')
        return redirect(url_for('main.index'))

    safe_course_name = plan_cadre.cours.nom.replace(' ', '_') if plan_cadre.cours else "Plan_Cadre"
    filename = f"Plan_Cadre_{plan_cadre.cours.code}_{safe_course_name}.docx" if plan_cadre.cours else f"Plan_Cadre_{plan_cadre.id}.docx"

    return send_file(
        docx_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


###############################################################################
# Édition d'un plan-cadre (exemple)
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
def edit_plan_cadre(plan_id):
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    form = PlanCadreForm()
    if request.method == 'GET':
        # Pré-remplir
        form.place_intro.data = plan_cadre.place_intro
        form.objectif_terminal.data = plan_cadre.objectif_terminal
        form.structure_intro.data = plan_cadre.structure_intro
        form.structure_activites_theoriques.data = plan_cadre.structure_activites_theoriques
        form.structure_activites_pratiques.data = plan_cadre.structure_activites_pratiques
        form.structure_activites_prevues.data = plan_cadre.structure_activites_prevues
        form.eval_evaluation_sommative.data = plan_cadre.eval_evaluation_sommative
        form.eval_nature_evaluations_sommatives.data = plan_cadre.eval_nature_evaluations_sommatives
        form.eval_evaluation_de_la_langue.data = plan_cadre.eval_evaluation_de_la_langue
        form.eval_evaluation_sommatives_apprentissages.data = plan_cadre.eval_evaluation_sommatives_apprentissages

        # Récupérer et remplir les FieldList
        # competences_developpees
        form.competences_developpees.entries = []
        for cdev in plan_cadre.competences_developpees:
            subform = form.competences_developpees.append_entry()
            subform.texte.data = cdev.texte
            subform.texte_description.data = cdev.description

        # objets_cibles
        form.objets_cibles.entries = []
        for oc in plan_cadre.objets_cibles:
            subform = form.objets_cibles.append_entry()
            subform.texte.data = oc.texte
            subform.texte_description.data = oc.description

        # cours_relies
        form.cours_relies.entries = []
        for cr in plan_cadre.cours_relies:
            subform = form.cours_relies.append_entry()
            subform.texte.data = cr.texte
            subform.texte_description.data = cr.description

        # cours_prealables
        form.cours_prealables.entries = []
        for cp in plan_cadre.cours_prealables:
            subform = form.cours_prealables.append_entry()
            subform.texte.data = cp.texte
            subform.texte_description.data = cp.description

        # savoir_etre
        form.savoir_etre.entries = []
        for se_ in plan_cadre.savoirs_etre:
            subform = form.savoir_etre.append_entry()
            subform.texte.data = se_.texte

        # competences_certifiees
        form.competences_certifiees.entries = []
        for cc in plan_cadre.competences_certifiees:
            subform = form.competences_certifiees.append_entry()
            subform.texte.data = cc.texte
            subform.texte_description.data = cc.description

        # cours_corequis
        form.cours_corequis.entries = []
        for cc in plan_cadre.cours_corequis:
            subform = form.cours_corequis.append_entry()
            subform.texte.data = cc.texte
            subform.texte_description.data = cc.description

    elif form.validate_on_submit():
        try:
            plan_cadre.place_intro = form.place_intro.data
            plan_cadre.objectif_terminal = form.objectif_terminal.data
            plan_cadre.structure_intro = form.structure_intro.data
            plan_cadre.structure_activites_theoriques = form.structure_activites_theoriques.data
            plan_cadre.structure_activites_pratiques = form.structure_activites_pratiques.data
            plan_cadre.structure_activites_prevues = form.structure_activites_prevues.data
            plan_cadre.eval_evaluation_sommative = form.eval_evaluation_sommative.data
            plan_cadre.eval_nature_evaluations_sommatives = form.eval_nature_evaluations_sommatives.data
            plan_cadre.eval_evaluation_de_la_langue = form.eval_evaluation_de_la_langue.data
            plan_cadre.eval_evaluation_sommatives_apprentissages = form.eval_evaluation_sommatives_apprentissages.data

            # Vider les relations existantes
            plan_cadre.competences_developpees.clear()
            plan_cadre.objets_cibles.clear()
            plan_cadre.cours_relies.clear()
            plan_cadre.cours_prealables.clear()
            plan_cadre.savoirs_etre.clear()
            plan_cadre.competences_certifiees.clear()
            plan_cadre.cours_corequis.clear()

            # competences_developpees
            for cdev_data in form.competences_developpees.data:
                t = cdev_data['texte']
                d = cdev_data['texte_description']
                plan_cadre.competences_developpees.append(
                    PlanCadreCompetencesDeveloppees(texte=t, description=d)
                )

            # objets_cibles
            for oc_data in form.objets_cibles.data:
                t = oc_data['texte']
                d = oc_data['texte_description']
                plan_cadre.objets_cibles.append(
                    PlanCadreObjetsCibles(texte=t, description=d)
                )

            # cours_relies
            for cr_data in form.cours_relies.data:
                t = cr_data['texte']
                d = cr_data['texte_description']
                plan_cadre.cours_relies.append(
                    PlanCadreCoursRelies(texte=t, description=d)
                )

            # cours_prealables
            for cp_data in form.cours_prealables.data:
                t = cp_data['texte']
                d = cp_data['texte_description']
                plan_cadre.cours_prealables.append(
                    PlanCadreCoursPrealables(texte=t, description=d)
                )

            # savoir_etre
            for se_data in form.savoir_etre.data:
                t = se_data['texte']
                if t.strip():
                    plan_cadre.savoirs_etre.append(
                        PlanCadreSavoirEtre(texte=t)
                    )

            # competences_certifiees
            for cc_data in form.competences_certifiees.data:
                t = cc_data['texte']
                d = cc_data['texte_description']
                plan_cadre.competences_certifiees.append(
                    PlanCadreCompetencesCertifiees(texte=t, description=d)
                )

            # cours_corequis
            for cc_data in form.cours_corequis.data:
                t = cc_data['texte']
                d = cc_data['texte_description']
                plan_cadre.cours_corequis.append(
                    PlanCadreCoursCorequis(texte=t, description=d)
                )

            db.session.commit()
            flash("Plan Cadre mis à jour avec succès!", 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_id))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Erreur update plan_cadre {plan_id}: {e}")
            traceback.print_exc()
            flash(f"Erreur lors de la mise à jour du Plan Cadre : {str(e)}", 'danger')

    return render_template('edit_plan_cadre.html', form=form, plan_id=plan_id, plan=plan_cadre)


###############################################################################
# Supprimer un plan-cadre
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/delete', methods=['POST'])
@role_required('admin')
def delete_plan_cadre(plan_id):
    form = DeleteForm()
    if form.validate_on_submit():
        plan_cadre = PlanCadre.query.get(plan_id)
        if not plan_cadre:
            flash('Plan Cadre non trouvé.', 'danger')
            return redirect(url_for('main.index'))

        cours_id = plan_cadre.cours_id
        try:
            db.session.delete(plan_cadre)
            db.session.commit()
            flash('Plan Cadre supprimé avec succès!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la suppression du Plan Cadre : {e}', 'danger')

        return redirect(url_for('cours.view_cours', cours_id=cours_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        return redirect(url_for('main.index'))


###############################################################################
# Ajouter une Capacité
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/add_capacite', methods=['GET', 'POST'])
@role_required('admin')
def add_capacite(plan_id):
    form = CapaciteForm()
    plan_cadre = PlanCadre.query.get(plan_id)
    if not plan_cadre:
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'GET':
        form.capacite.data = ""
        form.description_capacite.data = ""
        form.ponderation_min.data = 0
        form.ponderation_max.data = 0

    if form.validate_on_submit():
        try:
            cap = form.capacite.data.strip()
            desc = form.description_capacite.data.strip()
            pmin = form.ponderation_min.data
            pmax = form.ponderation_max.data

            if pmin > pmax:
                flash('La pondération minimale ne peut pas être supérieure à la pondération maximale.', 'danger')
                return redirect(url_for('plan_cadre.add_capacite', plan_id=plan_id))

            new_cap = PlanCadreCapacites(
                plan_cadre_id=plan_cadre.id,
                capacite=cap,
                description_capacite=desc,
                ponderation_min=pmin,
                ponderation_max=pmax
            )
            db.session.add(new_cap)
            db.session.commit()
            flash('Capacité ajoutée avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_cadre.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de la capacité : {e}', 'danger')

    return render_template(
        'add_capacite.html',
        form=form,
        plan_id=plan_id,
        cours_id=plan_cadre.cours_id
    )


###############################################################################
# Supprimer une Capacité
###############################################################################
@plan_cadre_bp.route('/<int:plan_id>/capacite/<int:capacite_id>/delete', methods=['POST'])
@role_required('admin')
def delete_capacite(plan_id, capacite_id):
    form = DeleteForm(prefix=f"capacite-{capacite_id}")
    if form.validate_on_submit():
        plan_cadre = PlanCadre.query.get(plan_id)
        if not plan_cadre:
            flash('Plan Cadre non trouvé.', 'danger')
            return redirect(url_for('main.index'))

        cours_id = plan_cadre.cours_id

        try:
            cap = PlanCadreCapacites.query.filter_by(id=capacite_id, plan_cadre_id=plan_id).first()
            if cap:
                db.session.delete(cap)
                db.session.commit()
                flash('Capacité supprimée avec succès!', 'success')
            else:
                flash('Capacité introuvable.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la suppression de la capacité : {e}', 'danger')

        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        plan_cadre = PlanCadre.query.get(plan_id)
        if plan_cadre:
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan_cadre.cours_id, plan_id=plan_id))
        return redirect(url_for('main.index'))
