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
from models import User

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



@plan_cadre_bp.route('/<int:plan_id>/generate_content', methods=['POST'])
@role_required('admin')
def generate_plan_cadre_content(plan_id):
    """
    Gère la génération du contenu d’un plan-cadre via GPT.
    Récupère toutes les sections (IDs 43 à 63), applique ou non l’IA
    selon 'use_ai', et insère dans les tables adéquates.
    """
    conn = get_db_connection()
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()

    if not plan:
        conn.close()
        flash('Plan Cadre non trouvé.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=0, plan_id=plan_id))

    user_id = current_user.id  # ou current_user.id si vous utilisez flask_login
    user = conn.execute('SELECT openai_key FROM User WHERE id = ?', (user_id,)).fetchone()
    openai_key = user['openai_key'] if user else None

    if not openai_key:
        conn.close()
        flash('Aucune clé OpenAI configurée.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    form = GenerateContentForm()
    if not form.validate_on_submit():
        conn.close()
        flash('Erreur de validation du formulaire.', 'danger')
        return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

    try:
        additional_info = form.additional_info.data
        ai_model = form.ai_model.data  # "gpt-4o", "gpt-4o-mini", etc.

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

        # Récupérer tous les settings 43 → 63
        parametres_generation = conn.execute(
            "SELECT section, use_ai, text_content FROM GlobalGenerationSettings"
        ).fetchall()

        # Transformer en dict { "Intro et place du cours": {"use_ai":..., "text_content":...}, ... }
        parametres_dict = {
            row['section']: {
                'use_ai': row['use_ai'],
                'text_content': row['text_content']
            }
            for row in parametres_generation
        }

        plan_cadre_data = get_plan_cadre_data(plan['cours_id'])

        # ----------------------------------------------------------
        # 1A) Mapping : quel champ va où ?
        # ----------------------------------------------------------
        # 1. Champs stockés directement dans la table PlanCadre :
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

        # 2. Champs stockés dans d’autres tables (1-ligne):
        field_to_table_insert = {
            'Description des compétences développées': 'PlanCadreCompetencesDeveloppees',
            'Description des Compétences certifiées': 'PlanCadreCompetencesCertifiees',
            'Description des cours corequis': 'PlanCadreCoursCorequis',
            'Objets cibles': 'PlanCadreObjetsCibles',
            'Description des cours reliés': 'PlanCadreCoursRelies',
            'Description des cours préalables': 'PlanCadreCoursPrealables',
        }

        # On prévoira un traitement spécial pour : "Savoir-être", "Capacité et pondération",
        # et potentiellement "Savoirs nécessaires d'une capacité", "Savoirs faire d'une capacité", etc.
        # Selon votre logique, vous pouvez tout regrouper dans "Capacité et pondération".

        # ----------------------------------------------------------
        # 1B) Parcours des sections pour déterminer "AI vs direct"
        # ----------------------------------------------------------
        ai_fields = []
        ai_fields_with_description = []
        non_ai_updates_plan_cadre = []    # Liste de tuples (col_name, replaced_text)
        non_ai_inserts_other_table = []   # Liste de tuples (table_name, replaced_text)
        ai_savoir_etre = None
        ai_capacites_prompt = []

        def replace_jinja(text_):
            return replace_tags_jinja2(text_, plan_cadre_data)

        for section_name, conf_data in parametres_dict.items():
            raw_text = conf_data.get('text_content', "")
            replaced_text = replace_jinja(raw_text)
            is_ai = (conf_data.get('use_ai', 0) == 1)

            # 1) Champs PlanCadre ?
            if section_name in field_to_plan_cadre_column:
                col_name = field_to_plan_cadre_column[section_name]
                if is_ai:
                    ai_fields.append({"field_name": section_name, "prompt": replaced_text})
                else:
                    non_ai_updates_plan_cadre.append((col_name, replaced_text))

            # 2) Champs à insérer dans une autre table ?
            elif section_name in field_to_table_insert:
                table_name = field_to_table_insert[section_name]

                # --- Si c'est "Description des compétences développées" et qu'on veut ajouter 
                #     des infos provenant d'une autre table pour GPT, on fait le traitement ici:
                if section_name == "Objets cibles" and is_ai:
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})
                    print(ai_fields_with_description)


                if section_name == "Description des compétences développées" and is_ai:
                    # Récupérer les compétences pour le cours
                    # (Adaptez la requête à votre structure de DB)
                    competences = conn.execute("""
                        SELECT DISTINCT ec.competence_id, c.nom, c.code
                        FROM ElementCompetence ec
                        JOIN ElementCompetenceParCours ecp ON ec.id = ecp.element_competence_id
                        JOIN Competence c ON ec.competence_id = c.id
                        WHERE ecp.cours_id = ?
                        AND ecp.status = 'Développé significativement';  -- Par exemple, ou un autre statut pertinent

                    """, (plan['cours_id'],)).fetchall()

                    # On construit un petit texte qui liste les compétences
                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences développées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp['code']}: {comp['nom']}\n"
                    else:
                        competences_text = "\n(Aucune compétence de type 'developpee' trouvée pour ce cours)\n"

                    # On concatène ce texte à replaced_text pour le prompt
                    replaced_text += f"\n\n{competences_text}"

                    # On ajoute ensuite ce champ à la liste des champs IA
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des Compétences certifiées" and is_ai:
                    # Récupérer les compétences pour le cours
                    # (Adaptez la requête à votre structure de DB)
                    competences = conn.execute("""
                        SELECT DISTINCT ec.competence_id, c.nom, c.code
                        FROM ElementCompetence ec
                        JOIN ElementCompetenceParCours ecp ON ec.id = ecp.element_competence_id
                        JOIN Competence c ON ec.competence_id = c.id
                        WHERE ecp.cours_id = ?
                        AND ecp.status = 'Atteint';  -- Par exemple, ou un autre statut pertinent

                    """, (plan['cours_id'],)).fetchall()

                    # On construit un petit texte qui liste les compétences
                    competences_text = ""
                    if competences:
                        competences_text = "\nListe des compétences certifiées pour ce cours:\n"
                        for comp in competences:
                            competences_text += f"- {comp['code']}: {comp['nom']}\n"
                    else:
                        competences_text = "\n(Aucune compétence de type 'certifiées' trouvée pour ce cours)\n"

                    # On concatène ce texte à replaced_text pour le prompt
                    replaced_text += f"\n\n{competences_text}"

                    # On ajoute ensuite ce champ à la liste des champs IA
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des cours corequis" and is_ai:
                    # Récupérer les compétences pour le cours
                    # (Adaptez la requête à votre structure de DB)
                    cours = conn.execute("""
                        SELECT CoursCorequis.id, Cours.code, Cours.nom
                        FROM CoursCorequis
                        JOIN Cours ON CoursCorequis.cours_corequis_id = Cours.id
                        WHERE CoursCorequis.cours_id = ?
                    """, (plan['cours_id'],)).fetchall()

                    # On construit un petit texte qui liste les compétences
                    cours_text = ""
                    if cours:
                        cours_text = "\nListe des cours corequis pour ce cours:\n"
                        for c in cours:
                            cours_text += f"- {c['code']}: {c['nom']}\n"
                    else:
                        cours_text = "\n(Aucun cours corequis à ce cours)\n"

                    # On concatène ce texte à replaced_text pour le prompt
                    replaced_text += f"\n\n{cours_text}"

                    # On ajoute ensuite ce champ à la liste des champs IA
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

                if section_name == "Description des cours préalables" and is_ai:
                    # Récupérer les compétences pour le cours
                    # (Adaptez la requête à votre structure de DB)
                    cours = conn.execute("""
                        SELECT CoursPrealable.id, Cours.code, Cours.nom
                        FROM CoursPrealable
                        JOIN Cours ON CoursPrealable.cours_prealable_id = Cours.id
                        WHERE CoursPrealable.cours_id = ?
                    """, (plan['cours_id'],)).fetchall()

                    # On construit un petit texte qui liste les compétences
                    cours_text = ""
                    if cours:
                        cours_text = "\nListe des cours préalables pour ce cours:\n"
                        for c in cours:
                            cours_text += f"- {c['code']}: {c['nom']}\n"
                    else:
                        cours_text = "\n(Aucun cours préalables à ce cours)\n"

                    # On concatène ce texte à replaced_text pour le prompt
                    replaced_text += f"\n\n{cours_text}"

                    # On ajoute ensuite ce champ à la liste des champs IA
                    ai_fields_with_description.append({"field_name": section_name, "prompt": replaced_text})

            # 3) Champs spéciaux
            else:
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
                        # Insertion directe en base (plusieurs lignes ?)
                        # À vous de décider si text_content est déjà en CSV, etc.
                        # Exemple minimal : on suppose splitted par "\n"
                        lines = [l.strip() for l in replaced_text.split("\n") if l.strip()]
                        for line in lines:
                            conn.execute(
                                "INSERT INTO PlanCadreSavoirEtre (plan_cadre_id, texte) VALUES (?, ?)",
                                (plan_id, line)
                            )
                # Capacité et pondération
                elif section_name in target_sections:
                    if is_ai:
                        section_formatted = f"### {section_name}\n{replaced_text}"
                        ai_capacites_prompt.append(section_formatted)
                    else:
                        # Pas d'IA => insertion directe ? (À vous de voir)
                        pass

                else:
                    # Section inconnue : on l’ignore ou on gère autrement
                    pass

        # ----------------------------------------------------------
        # 1C) Exécuter les updates/inserts "non-AI" (direct)
        # ----------------------------------------------------------
        # - PlanCadre
        for col_name, val in non_ai_updates_plan_cadre:
            conn.execute(f"UPDATE PlanCadre SET {col_name} = ? WHERE id = ?", (val, plan_id))

        # - Autres tables
        for table_name, val in non_ai_inserts_other_table:
            # Exemple d’insertion (assurez-vous que la table a les colonnes voulues)
            conn.execute(
                f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (?, ?)",
                (plan_id, val)
            )

        # On commit les non-AI
        conn.commit()

        # ----------------------------------------------------------
        # 1D) Vérifier si on doit vraiment appeler GPT
        # ----------------------------------------------------------
        # => Si *aucun* champ n’est géré par l’IA, on sort
        if not ai_fields and not ai_savoir_etre and not ai_capacites_prompt:
            conn.close()
            flash('Aucune génération IA requise (tous champs non-AI).', 'success')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        schema_json = json.dumps(PlanCadreAIResponse.schema(), indent=4, ensure_ascii=False)

        # ----------------------------------------------------------
        # 2) Appel GPT (un seul)
        # ----------------------------------------------------------
        role_message = (
            f"Tu es un rédacteur de contenu pour un plan-cadre de cours '{cours_nom}', "
            f"session {cours_session}. Retourne un JSON valide correspondant à PlanCadreAIResponse."
        )

        # On structure la requête pour GPT
        structured_request = {
            "instruction": (
                f"Tu es un rédacteur de contenu pour un plan-cadre de cours '{cours_nom}', "
                f"session {cours_session}. Retourne un JSON valide correspondant à PlanCadreAIResponse."
                f"Informations supplémentaires: {additional_info}\n\n"
                "Voici le schéma JSON auquel ta réponse doit strictement adhérer :\n\n"
                f"{schema_json}\n\n"
                "Utilise un langage neutre (Par exemple 'étudiant' devrait être 'personne étudiante'.\n\n"

                "Voici différents prompts."
                f"- fields:{ai_fields}\n\n"
                f"- fields_with_description:{ai_fields_with_description}\n\n"
                f"- savoir_etre:{ai_savoir_etre}\n\n"
                f"- capacites:{ai_capacites_prompt}\n\n"
            )
        }

        print(json.dumps(structured_request, indent=4, ensure_ascii=False))

        # On suppose que vous avez la fonction openai qui gère l’API
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)

        try:
            o1_response = client.beta.chat.completions.parse(
                model=ai_model,  # ou "gpt-3.5-turbo"
                messages=[
                    {"role": "user", "content": json.dumps(structured_request)}
                ]
            )
        except Exception as e:
            conn.close()
            logging.error(f"OpenAI error: {e}")
            flash(f"Erreur API OpenAI: {str(e)}", 'danger')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        o1_response_content = o1_response.choices[0].message.content

        try:
            completion = client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user", 
                        "content": f"""
            Connaissant les données suivantes, formatte-les selon le response_format demandé: {o1_response_content}
            """
                    }
                ],
                response_format=PlanCadreAIResponse,
            )
        except Exception as e:
            conn.close()
            logging.error(f"OpenAI error: {e}")
            flash(f"Erreur API OpenAI: {str(e)}", 'danger')
            return redirect(url_for('cours.view_plan_cadre', plan_id=plan_id))

        # ----------------------------------------------------------
        # 3) Parse & insertion en base du retour GPT
        # ----------------------------------------------------------
        parsed_data: PlanCadreAIResponse = completion.choices[0].message.parsed

        #print(parsed_data)

        def clean_text(val):
            return val.strip().strip('"').strip("'") if val else ""

        # 3A) fields -> (PlanCadre ou autres tables)
        for fobj in (parsed_data.fields or []):
            fname = fobj.field_name
            fcontent = clean_text(fobj.content)
            raw_content = fobj.content  

            # Si c’est un champ de PlanCadre
            if fname in field_to_plan_cadre_column:
                col = field_to_plan_cadre_column[fname]
                conn.execute(
                    f"UPDATE PlanCadre SET {col} = ? WHERE id = ?", 
                    (fcontent, plan_id)
                )




        table_mapping = {
            "Description des compétences développées": "PlanCadreCompetencesDeveloppees",
            "Description des Compétences certifiées": "PlanCadreCompetencesCertifiees",
            "Description des cours corequis": "PlanCadreCoursCorequis",
            "Description des cours préalables": "PlanCadreCoursPrealables",
            "Objets cibles": "PlanCadreObjetsCibles"
        }

        for fobj in parsed_data.fields_with_description:
            fname = fobj.field_name  # Définir fname ici

            # Initialiser une liste vide pour les éléments à insérer
            elements = []

            # Vérifier si le contenu est présent
            if fobj.content:
                if isinstance(fobj.content, list):
                    # Si le contenu est une liste, itérer sur chaque élément
                    for item in fobj.content:
                        texte_comp = item.texte.strip() if item.texte else ""
                        desc_comp = item.description.strip() if item.description else ""
                        if texte_comp or desc_comp:
                            elements.append({"texte": texte_comp, "description": desc_comp})
                elif isinstance(fobj.content, str):
                    # Si le contenu est une chaîne de caractères, l'ajouter directement
                    elements.append({"texte": fobj.content.strip(), "description": ""})
            # Si le contenu est None ou vide, `elements` restera une liste vide

            # Vérifier si le champ doit être inséré dans une table spécifique
            if fname in field_to_table_insert:
                # Obtenir le nom de la table correspondante
                table_name = table_mapping.get(fname)
                if not table_name:
                    # Si le nom du champ n'est pas reconnu, passer au suivant
                    continue

                # Itérer sur chaque élément à insérer
                for elem in elements:
                    texte_comp = elem["texte"]
                    desc_comp = elem["description"]

                    # Vérifier si *les deux* champs sont vides
                    if not texte_comp and not desc_comp:
                        # Les deux sont vides => sauter cette insertion
                        continue

                    # Préparer la requête SQL en fonction de la table
                    insert_query = f"""
                        INSERT OR REPLACE INTO {table_name} (plan_cadre_id, texte, description)
                        VALUES (?, ?, ?)
                    """

                    # Exécuter l'insertion en base de données
                    conn.execute(
                        insert_query,
                        (plan_id, texte_comp, desc_comp)
                    )
            else:
                # Gérer les champs qui ne nécessitent pas d'insertion dans une table spécifique
                # Par exemple, les insérer dans une table générique ou les ignorer
                pass

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
                # Insert la capacité
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

                # Savoirs-faire (texte, cible, seuil_reussite)
                if cap.savoirs_faire:
                    for sf in cap.savoirs_faire:
                        cursor.execute("""
                            INSERT INTO PlanCadreCapaciteSavoirsFaire (capacite_id, texte, cible, seuil_reussite)
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

        flash('Contenu généré automatiquement avec succès!', 'success')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))

    except Exception as e:
        conn.close()
        logging.error(f"Unexpected error: {e}")
        flash(f'Erreur lors de la génération du contenu: {e}', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))



@plan_cadre_bp.route('/<int:plan_id>/export', methods=['GET'])
@login_required
def export_plan_cadre(plan_id):
    # Générer le fichier DOCX à partir du modèle
    docx_file = generate_docx_with_template(plan_id)
    
    if not docx_file:
        flash('Plan Cadre non trouvé', 'danger')
        return redirect(url_for('main.index'))

    # Renommer le fichier pour le téléchargement
    filename = f"Plan_Cadre_{plan_id}.docx"
    
    # Envoyer le fichier à l'utilisateur
    return send_file(docx_file, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

@plan_cadre_bp.route('/<int:plan_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
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