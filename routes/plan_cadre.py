# plan_cadre.py
from flask import Blueprint, Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from forms import (
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
    CoursPrealableForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm, 
    GenerationSettingForm
)
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
from pprint import pprint
import json
import logging
from collections import defaultdict
from openai import OpenAI
from openai import OpenAIError
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
from decorator import role_required, roles_required
import bleach
from docxtpl import DocxTemplate
from io import BytesIO 
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_db_connection, parse_html_to_list, parse_html_to_nested_list, get_plan_cadre_data, replace_tags_jinja2, process_ai_prompt, generate_docx_with_template
from models import User, PlanCadre

class AIField(BaseModel):
    """Represents older PlanCadre fields (e.g. place_intro, objectif_terminal)."""
    field_name: Optional[str] = None
    content: Optional[str] = None

class AIContentDetail(BaseModel):
    texte: Optional[str] = None
    description: Optional[str] = None

class AIFieldWithDescription(BaseModel):
    field_name: Optional[str] = None
    content: Optional[List[AIContentDetail]] = None  # Permet une liste d'objets structurés pour certains champs

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
      - savoir_etre: (list of strings)
      - capacites: (list of AICapacite)
    """
    fields: Optional[List[AIField]] = None
    fields_with_description: Optional[List[AIFieldWithDescription]] = None
    savoir_etre: Optional[List[str]] = None
    capacites: Optional[List[AICapacite]] = None


# Configure logging
logging.basicConfig(level=logging.ERROR, filename='app_errors.log', filemode='a', 
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
    
    Args:
        usage_prompt (int): Nombre de tokens en entrée
        usage_completion (int): Nombre de tokens en sortie
        model (str): Identifiant du modèle utilisé
        
    Returns:
        float: Coût total de l'appel
    """
    if model not in MODEL_PRICING:
        raise ValueError(f"Modèle {model} non trouvé dans la grille tarifaire")
        
    pricing = MODEL_PRICING[model]
    
    # Le pricing est déjà en $/token (après division par 1M dans MODEL_PRICING)
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
    conn = get_db_connection()
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()

    if not plan:
        conn.close()
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=0, plan_id=plan_id))

    user_id = current_user.id
    user = conn.execute('SELECT openai_key, credits FROM User WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        flash('Utilisateur introuvable.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    openai_key = user['openai_key']
    user_credits = user['credits']  # Le nombre de crédits restants

    if not openai_key:
        conn.close()
        flash('Aucune clé OpenAI configurée dans votre profil.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    # Vérification basique : l'utilisateur doit avoir > 0 crédits pour tenter la requête
    if user_credits <= 0:
        conn.close()
        flash('Vous n’avez plus de crédits pour effectuer un appel OpenAI.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    form = GenerateContentForm()
    if not form.validate_on_submit():
        conn.close()
        flash('Erreur de validation du formulaire.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

    try:
        additional_info = form.additional_info.data
        ai_model = form.ai_model.data  # ex : "gpt-4o", "gpt-4o-mini", "o1-preview", "o1-mini", etc.

        # Sauvegarder les données supplémentaires dans la base de données
        conn.execute(
            "UPDATE PlanCadre SET additional_info = ?, ai_model = ? WHERE id = ?",
            (additional_info, ai_model, plan_id)
        )

        # ----------------------------------------------------------
        # 1) Préparation des data & des settings
        # ----------------------------------------------------------
        cours = conn.execute('SELECT nom, session FROM Cours WHERE id = ?', (plan['cours_id'],)).fetchone()
        cours_nom = cours['nom'] if cours else "Non défini"
        cours_session = cours['session'] if (cours and cours['session']) else "Non défini"

        # Récupérer les paramètres 43 → 63
        parametres_generation = conn.execute(
            "SELECT section, use_ai, text_content FROM GlobalGenerationSettings"
        ).fetchall()

        parametres_dict = {
            row['section']: {
                'use_ai': row['use_ai'],
                'text_content': row['text_content']
            }
            for row in parametres_generation
        }

        plan_cadre_data = get_plan_cadre_data(plan['cours_id'])

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

        for section_name, conf_data in parametres_dict.items():
            raw_text = conf_data.get('text_content', "")
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
                    competences = conn.execute("""
                        SELECT DISTINCT ec.competence_id, c.nom, c.code
                          FROM ElementCompetence ec
                          JOIN ElementCompetenceParCours ecp ON ec.id = ecp.element_competence_id
                          JOIN Competence c ON ec.competence_id = c.id
                         WHERE ecp.cours_id = ?
                           AND ecp.status = 'Développé significativement';
                    """, (plan['cours_id'],)).fetchall()

                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences développées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp['code']}: {comp['nom']}\n"
                    else:
                        competences_text = "\n(Aucune compétence de type 'developpee' trouvée)\n"

                    replaced_text += f"\n\n{competences_text}"
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des Compétences certifiées" and is_ai:
                    # Récupérer les compétences "certifiées"
                    competences = conn.execute("""
                        SELECT DISTINCT ec.competence_id, c.nom, c.code
                          FROM ElementCompetence ec
                          JOIN ElementCompetenceParCours ecp ON ec.id = ecp.element_competence_id
                          JOIN Competence c ON ec.competence_id = c.id
                         WHERE ecp.cours_id = ?
                           AND ecp.status = 'Atteint';
                    """, (plan['cours_id'],)).fetchall()

                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences certifiées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp['code']}: {comp['nom']}\n"
                    else:
                        competences_text = "\n(Aucune compétence 'certifiée' trouvée)\n"

                    replaced_text += f"\n\n{competences_text}"
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des cours corequis" and is_ai:
                    # Récupérer les cours corequis
                    corequis = conn.execute("""
                        SELECT CoursCorequis.id, Cours.code, Cours.nom
                          FROM CoursCorequis
                          JOIN Cours ON CoursCorequis.cours_corequis_id = Cours.id
                         WHERE CoursCorequis.cours_id = ?
                    """, (plan['cours_id'],)).fetchall()

                    cours_text = ""
                    if corequis:
                        cours_text = "\nListe des cours corequis:\n"
                        for c in corequis:
                            cours_text += f"- {c['code']}: {c['nom']}\n"
                    else:
                        cours_text = "\n(Aucun cours corequis)\n"

                    replaced_text += f"\n\n{cours_text}"
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des cours préalables" and is_ai:
                    # Récupérer les cours pour lesquels ce cours est un prérequis
                    prealables = conn.execute("""
                        SELECT CoursPrealable.id, Cours.code, Cours.nom, CoursPrealable.note_necessaire
                          FROM CoursPrealable
                          JOIN Cours ON CoursPrealable.cours_id = Cours.id
                         WHERE CoursPrealable.cours_prealable_id = ?
                    """, (plan['cours_id'],)).fetchall()

                    cours_text = ""
                    if prealables:
                        cours_text = "\nCe cours est un prérequis pour:\n"
                        for c in prealables:
                            note = f" (note requise: {c['note_necessaire']}%)" if c['note_necessaire'] else ""
                            cours_text += f"- {c['code']}: {c['nom']}{note}\n"
                    else:
                        cours_text = "\n(Ce cours n'est prérequis pour aucun autre cours)\n"

                    replaced_text += f"\n\n{cours_text}"
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                # Sinon, si non IA :
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
                        # Insertion directe
                        lines = [l.strip() for l in replaced_text.split("\n") if l.strip()]
                        for line in lines:
                            conn.execute(
                                "INSERT INTO PlanCadreSavoirEtre (plan_cadre_id, texte) VALUES (?, ?)",
                                (plan_id, line)
                            )
                # Capacités
                elif section_name in target_sections:
                    if is_ai:
                        section_formatted = f"### {section_name}\n{replaced_text}"
                        ai_capacites_prompt.append(section_formatted)
                    else:
                        # Pas d'IA => insertion directe ? (A adapter)
                        pass
                else:
                    # Section inconnue => on ignore ou on gère autrement
                    pass

        # ----------------------------------------------------------
        # 1C) Exécuter les updates/inserts "non-AI" (direct)
        # ----------------------------------------------------------
        for col_name, val in non_ai_updates_plan_cadre:
            conn.execute(f"UPDATE PlanCadre SET {col_name} = ? WHERE id = ?", (val, plan_id))

        for table_name, val in non_ai_inserts_other_table:
            conn.execute(
                f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (?, ?)",
                (plan_id, val)
            )
        conn.commit()

        # ----------------------------------------------------------
        # 1D) Vérifier si on doit appeler GPT
        # ----------------------------------------------------------
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt and not ai_fields_with_description:
            conn.close()
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
            conn.close()
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
            conn.close()
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
        #  - Premier appel : model=ai_model => on utilise MODEL_PRICING[ai_model]
        #  - Second appel : model="gpt-4o"
        # Comme on a fait deux appels séparés, 
        # on peut calculer le coût *global* en proportion 
        # ou simplement tout imputer au second modèle. 
        #
        # Si vous voulez un calcul précis par appel:
        #    => Il faut séparer l'usage du premier et du second. 
        # Pour simplifier, on va tout cumuler puis répartir 
        # (ou vous faites un second bloc avec un nouveau total).
        #
        # Ici, on va "bidouiller" un cumul. 
        # Pour être rigoureux:
        #   *1er appel => usage1 = (p1, c1), on applique le pricing du ai_model
        #   *2e appel => usage2 = (p2, c2), on applique le pricing "gpt-4o"
        #   => total = cost1 + cost2
        #
        # Exemple :
        try:
            # Premier appel (avec le modèle choisi par l'utilisateur)
            usage_1_prompt = o1_response.usage.prompt_tokens if hasattr(o1_response, 'usage') else 0
            usage_1_completion = o1_response.usage.completion_tokens if hasattr(o1_response, 'usage') else 0
            cost_first_call = calculate_call_cost(usage_1_prompt, usage_1_completion, ai_model)
            
            # Second appel (toujours avec gpt-4o)
            usage_2_prompt = completion.usage.prompt_tokens if hasattr(completion, 'usage') else 0
            usage_2_completion = completion.usage.completion_tokens if hasattr(completion, 'usage') else 0
            cost_second_call = calculate_call_cost(usage_2_prompt, usage_2_completion, "gpt-4o")
            
            # Coût total
            total_cost = cost_first_call + cost_second_call
            
            # Log pour debug
            print(f"Premier appel ({ai_model}): {cost_first_call:.6f}$ ({usage_1_prompt} prompt, {usage_1_completion} completion)")
            print(f"Second appel (gpt-4o): {cost_second_call:.6f}$ ({usage_2_prompt} prompt, {usage_2_completion} completion)")
            print(f"Coût total: {total_cost:.6f}$")
            
            # Mise à jour des crédits
            new_credits = user_credits - total_cost
            
            if new_credits < 0:
                raise ValueError("Crédits insuffisants pour effectuer l'opération")
                
            conn.execute("UPDATE User SET credits = ? WHERE id = ?", (new_credits, user_id))
            conn.commit()
            
        except ValueError as ve:
            conn.close()
            flash(str(ve), 'danger')
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

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
                conn.execute(
                    f"UPDATE PlanCadre SET {col} = ? WHERE id = ?",
                    (fcontent, plan_id)
                )

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

            # fobj.content peut être une liste ou une str
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
                conn.execute(f"""
                    INSERT OR REPLACE INTO {table_name} (plan_cadre_id, texte, description)
                    VALUES (?, ?, ?)
                """, (plan_id, texte_comp, desc_comp))

        # 3B) savoir_etre -> PlanCadreSavoirEtre
        if parsed_data.savoir_etre:
            for se_item in parsed_data.savoir_etre:
                conn.execute(
                    "INSERT INTO PlanCadreSavoirEtre (plan_cadre_id, texte) VALUES (?, ?)",
                    (plan_id, clean_text(se_item))
                )

        # 3C) capacites -> PlanCadreCapacites + sous-tables
        if parsed_data.capacites:
            cursor = conn.cursor()
            for cap in parsed_data.capacites:
                cursor.execute("""
                    INSERT INTO PlanCadreCapacites 
                        (plan_cadre_id, capacite, description_capacite, ponderation_min, ponderation_max)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    plan_id,
                    clean_text(cap.capacite),
                    clean_text(cap.description_capacite),
                    cap.ponderation_min if cap.ponderation_min else 0,
                    cap.ponderation_max if cap.ponderation_max else 0
                ))
                new_cap_id = cursor.lastrowid

                # Savoirs nécessaires
                if cap.savoirs_necessaires:
                    for sn in cap.savoirs_necessaires:
                        cursor.execute("""
                            INSERT INTO PlanCadreCapaciteSavoirsNecessaires (capacite_id, texte)
                            VALUES (?, ?)
                        """, (new_cap_id, clean_text(sn)))

                # Savoirs-faire
                if cap.savoirs_faire:
                    for sf in cap.savoirs_faire:
                        cursor.execute("""
                            INSERT INTO PlanCadreCapaciteSavoirsFaire 
                                (capacite_id, texte, cible, seuil_reussite)
                            VALUES (?, ?, ?, ?)
                        """, (
                            new_cap_id,
                            clean_text(sf.texte),
                            clean_text(sf.cible),
                            clean_text(sf.seuil_reussite)
                        ))

                # Moyens d'évaluation
                if cap.moyens_evaluation:
                    for me in cap.moyens_evaluation:
                        cursor.execute("""
                            INSERT INTO PlanCadreCapaciteMoyensEvaluation (capacite_id, texte)
                            VALUES (?, ?)
                        """, (new_cap_id, clean_text(me)))

        conn.commit()
        conn.close()

        flash(f'Contenu généré automatiquement avec succès! Coût total: {round(total_cost, 4)} crédits.', 'success')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    except Exception as e:
        conn.close()
        logging.error(f"Unexpected error: {e}")
        flash(f'Erreur lors de la génération du contenu: {e}', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))



@plan_cadre_bp.route('/<int:plan_id>/export', methods=['GET'])
@login_required
def export_plan_cadre(plan_id):
    # Récupérer le plan cadre avec le cours associé
    plan_cadre = PlanCadre.query.get(plan_id)
    
    if not plan_cadre:
        flash('Plan Cadre non trouvé', 'danger')
        return redirect(url_for('main.index'))
    
    # Générer le fichier DOCX à partir du modèle
    docx_file = generate_docx_with_template(plan_id)
    
    if not docx_file:
        flash('Erreur lors de la génération du document', 'danger')
        return redirect(url_for('main.index'))
    
    # Créer un nom de fichier sécurisé avec le code et le nom du cours
    safe_course_name = plan_cadre.cours.nom.replace(' ', '_')
    filename = f"Plan_Cadre_{plan_cadre.cours.code}_{safe_course_name}.docx"
    
    # Envoyer le fichier à l'utilisateur
    return send_file(docx_file, 
                    as_attachment=True, 
                    download_name=filename,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    

@plan_cadre_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
def edit_plan_cadre(plan_id):
    form = PlanCadreForm()
    conn = get_db_connection()
    
    # Récupérer les informations existantes du Plan Cadre
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
    
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))
    
    if request.method == 'GET':
        # Remplir les champs principaux
        form.place_intro.data = plan['place_intro']
        form.objectif_terminal.data = plan['objectif_terminal']
        form.structure_intro.data = plan['structure_intro']
        form.structure_activites_theoriques.data = plan['structure_activites_theoriques']
        form.structure_activites_pratiques.data = plan['structure_activites_pratiques']
        form.structure_activites_prevues.data = plan['structure_activites_prevues']
        form.eval_evaluation_sommative.data = plan['eval_evaluation_sommative']
        form.eval_nature_evaluations_sommatives.data = plan['eval_nature_evaluations_sommatives']
        form.eval_evaluation_de_la_langue.data = plan['eval_evaluation_de_la_langue']
        form.eval_evaluation_sommatives_apprentissages.data = plan['eval_evaluation_sommatives_apprentissages']
        
        # Récupérer les données existantes pour les FieldList
        competences_developpees = conn.execute('SELECT texte, description FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        objets_cibles = conn.execute('SELECT texte, description FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        cours_relies = conn.execute('SELECT texte, description FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        cours_prealables = conn.execute('SELECT texte, description FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        savoir_etre = conn.execute('SELECT texte FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        
        # Nouveaux champs récupérés
        competences_certifiees = conn.execute('SELECT texte, description FROM PlanCadreCompetencesCertifiees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        cours_corequis = conn.execute('SELECT texte, description FROM PlanCadreCoursCorequis WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
        
        # Remplir les FieldList avec les données existantes
        # Compétences Développées
        form.competences_developpees.entries = []
        for c in competences_developpees:
            subform = form.competences_developpees.append_entry()
            subform.texte.data = c['texte']
            subform.texte_description.data = c['description']
        
        # Objets Cibles
        form.objets_cibles.entries = []
        for o in objets_cibles:
            subform = form.objets_cibles.append_entry()
            subform.texte.data = o['texte']
            subform.texte_description.data = o['description']
        
        # Cours Reliés
        form.cours_relies.entries = []
        for cr in cours_relies:
            subform = form.cours_relies.append_entry()
            subform.texte.data = cr['texte']
            subform.texte_description.data = cr['description']
        
        # Cours Préalables
        form.cours_prealables.entries = []
        for cp in cours_prealables:
            subform = form.cours_prealables.append_entry()
            subform.texte.data = cp['texte']
            subform.texte_description.data = cp['description']
        
        # Savoir-être
        form.savoir_etre.entries = []
        for se in savoir_etre:
            subform = form.savoir_etre.append_entry()
            subform.texte.data = se['texte']
        
        # Remplir Compétences Certifiées
        form.competences_certifiees.entries = []
        for cc in competences_certifiees:
            subform = form.competences_certifiees.append_entry()
            subform.texte.data = cc['texte']
            subform.texte_description.data = cc['description']
        
        # Remplir Cours Corequis
        form.cours_corequis.entries = []
        for cc in cours_corequis:
            subform = form.cours_corequis.append_entry()
            subform.texte.data = cc['texte']
            subform.texte_description.data = cc['description']
    
    if form.validate_on_submit():
        # Récupérer les nouvelles données du formulaire
        place_intro = form.place_intro.data
        objectif_terminal = form.objectif_terminal.data
        structure_intro = form.structure_intro.data
        structure_activites_theoriques = form.structure_activites_theoriques.data
        structure_activites_pratiques = form.structure_activites_pratiques.data
        structure_activites_prevues = form.structure_activites_prevues.data
        eval_evaluation_sommative = form.eval_evaluation_sommative.data
        eval_nature_evaluations_sommatives = form.eval_nature_evaluations_sommatives.data
        eval_evaluation_de_la_langue = form.eval_evaluation_de_la_langue.data
        eval_evaluation_sommatives_apprentissages = form.eval_evaluation_sommatives_apprentissages.data
        
        # Récupérer les données des FieldList
        competences_developpees_data = form.competences_developpees.data
        objets_cibles_data = form.objets_cibles.data
        cours_relies_data = form.cours_relies.data
        cours_prealables_data = form.cours_prealables.data
        savoir_etre_data = form.savoir_etre.data
        competences_certifiees_data = form.competences_certifiees.data
        cours_corequis_data = form.cours_corequis.data
        
        # Obtenir le cours_id associé au plan_cadre
        cours_id = plan['cours_id']
        
        try:
            # Mettre à jour le Plan Cadre
            conn.execute("""
                UPDATE PlanCadre 
                SET place_intro = ?, objectif_terminal = ?, structure_intro = ?, 
                    structure_activites_theoriques = ?, structure_activites_pratiques = ?, 
                    structure_activites_prevues = ?, eval_evaluation_sommative = ?, 
                    eval_nature_evaluations_sommatives = ?, eval_evaluation_de_la_langue = ?, 
                    eval_evaluation_sommatives_apprentissages = ?
                WHERE id = ?
            """, (
                place_intro, objectif_terminal, structure_intro, structure_activites_theoriques, 
                structure_activites_pratiques, structure_activites_prevues, eval_evaluation_sommative, 
                eval_nature_evaluations_sommatives, eval_evaluation_de_la_langue, 
                eval_evaluation_sommatives_apprentissages, plan_id
            ))
            
            # Mettre à jour les compétences développées
            conn.execute('DELETE FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', (plan_id,))
            for competence in competences_developpees_data:
                conn.execute('''
                    INSERT INTO PlanCadreCompetencesDeveloppees (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, competence['texte'], competence['texte_description']))
    
            # Mettre à jour les objets cibles
            conn.execute('DELETE FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,))
            for objet in objets_cibles_data:
                conn.execute('''
                    INSERT INTO PlanCadreObjetsCibles (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, objet['texte'], objet['texte_description']))
    
            # Mettre à jour les cours reliés
            conn.execute('DELETE FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,))
            for cr in cours_relies_data:
                conn.execute('''
                    INSERT INTO PlanCadreCoursRelies (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, cr['texte'], cr['texte_description']))
    
            # Mettre à jour les cours préalables
            conn.execute('DELETE FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', (plan_id,))
            for cp in cours_prealables_data:
                conn.execute('''
                    INSERT INTO PlanCadreCoursPrealables (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, cp['texte'], cp['texte_description']))
    
            # Mettre à jour le savoir-être
            conn.execute('DELETE FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,))
            for se in savoir_etre_data:
                texte = se.get('texte')
                if texte and texte.strip():
                    conn.execute('''
                        INSERT INTO PlanCadreSavoirEtre (plan_cadre_id, texte) 
                        VALUES (?, ?)
                    ''', (plan_id, texte.strip()))
    
            # Mettre à jour les compétences certifiées
            conn.execute('DELETE FROM PlanCadreCompetencesCertifiees WHERE plan_cadre_id = ?', (plan_id,))
            for cc in competences_certifiees_data:
                conn.execute('''
                    INSERT INTO PlanCadreCompetencesCertifiees (plan_cadre_id, texte, description)
                    VALUES (?, ?, ?)
                ''', (plan_id, cc['texte'], cc['texte_description']))
    
            # Mettre à jour les cours corequis
            conn.execute('DELETE FROM PlanCadreCoursCorequis WHERE plan_cadre_id = ?', (plan_id,))
            for cc in cours_corequis_data:
                conn.execute('''
                    INSERT INTO PlanCadreCoursCorequis (plan_cadre_id, texte, description)
                    VALUES (?, ?, ?)
                ''', (plan_id, cc['texte'], cc['texte_description']))
    
            conn.commit()
            flash('Plan Cadre mis à jour avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de la mise à jour du Plan Cadre : {e}', 'danger')
        finally:
            conn.close()
    
    conn.close()
    return render_template('edit_plan_cadre.html', form=form, plan_id=plan_id, plan=plan)

# Route pour supprimer un Plan Cadre
@plan_cadre_bp.route('/<int:plan_id>/delete', methods=['POST'])
@role_required('admin')
def delete_plan_cadre(plan_id):
    form = DeleteForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        plan = conn.execute('SELECT cours_id FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
        if not plan:
            flash('Plan Cadre non trouvé.', 'danger')
            conn.close()
            return redirect(url_for('main.index'))
        
        cours_id = plan['cours_id']
        try:
            conn.execute('DELETE FROM PlanCadre WHERE id = ?', (plan_id,))
            conn.commit()
            flash('Plan Cadre supprimé avec succès!', 'success')
        except sqlite3.Error as e:
            flash(f'Erreur lors de la suppression du Plan Cadre : {e}', 'danger')
        finally:
            conn.close()
        
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        return redirect(url_for('main.index'))

# Route pour ajouter une capacité au Plan Cadre
@plan_cadre_bp.route('/<int:plan_id>/add_capacite', methods=['GET', 'POST'])
@role_required('admin')
def add_capacite(plan_id):
    form = CapaciteForm()
    conn = get_db_connection()
    
    # Récupérer le Plan Cadre pour obtenir le cours_id
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
    
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))
    
    cours_id = plan['cours_id']
    
    if form.validate_on_submit():
        capacite = form.capacite.data
        description = form.description_capacite.data
        ponderation_min = form.ponderation_min.data
        ponderation_max = form.ponderation_max.data

        if ponderation_min > ponderation_max:
            flash('La pondération minimale ne peut pas être supérieure à la pondération maximale.', 'danger')
            return redirect(url_for('main.add_capacite', plan_id=plan_id))

        try:
            conn.execute("""
                INSERT INTO PlanCadreCapacites 
                (plan_cadre_id, capacite, description_capacite, ponderation_min, ponderation_max)
                VALUES (?, ?, ?, ?, ?)
            """, (plan_id, capacite, description, ponderation_min, ponderation_max))
            conn.commit()
            flash('Capacité ajoutée avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de l\'ajout de la capacité : {e}', 'danger')
        finally:
            conn.close()
    
    # Pour les requêtes GET, vous pouvez pré-remplir le formulaire si nécessaire
    if request.method == 'GET':
        form.capacite.data = ''
        form.description_capacite.data = ''
        form.ponderation_min.data = 0
        form.ponderation_max.data = 0
    
    conn.close()
    # Passer également 'cours_id' au template
    return render_template('add_capacite.html', form=form, plan_id=plan_id, cours_id=cours_id)


@plan_cadre_bp.route('/<int:plan_id>/capacite/<int:capacite_id>/delete', methods=['POST'])
@role_required('admin')
def delete_capacite(plan_id, capacite_id):
    # Utiliser le même préfixe que lors de la création du formulaire
    form = DeleteForm(prefix=f"capacite-{capacite_id}")
    if form.validate_on_submit():
        conn = get_db_connection()
        # Récupérer le cours_id associé au plan_id pour la redirection
        plan = conn.execute('SELECT cours_id FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
        if not plan:
            flash('Plan Cadre non trouvé.', 'danger')
            conn.close()
            return redirect(url_for('main.index'))
        
        cours_id = plan['cours_id']

        try:
            conn.execute('DELETE FROM PlanCadreCapacites WHERE id = ?', (capacite_id,))
            conn.commit()
            flash('Capacité supprimée avec succès!', 'success')
        except sqlite3.Error as e:
            flash(f'Erreur lors de la suppression de la capacité : {e}', 'danger')
        finally:
            conn.close()
        
        # Rediriger vers view_plan_cadre avec cours_id et plan_id
        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        # Il faut aussi rediriger correctement ici
        conn = get_db_connection()
        plan = conn.execute('SELECT cours_id FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
        conn.close()
        if plan:
            return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))
        else:
            return redirect(url_for('main.index'))