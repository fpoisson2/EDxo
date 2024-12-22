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
    CapaciteForm,
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
import json
import logging
from collections import defaultdict
from openai import OpenAI
from openai import OpenAIError
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
import bleach
from docxtpl import DocxTemplate
from io import BytesIO 
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_db_connection, parse_html_to_list, parse_html_to_nested_list, get_plan_cadre_data, replace_tags_jinja2, process_ai_prompt, generate_docx_with_template
from models import User


plan_cadre_bp = Blueprint('plan_cadre', __name__)

@plan_cadre_bp.route('/<int:plan_id>/generate_content', methods=['POST'])
@login_required
def generate_plan_cadre_content(plan_id):
    form = GenerateContentForm()
    if form.validate_on_submit():
        try:
            # Connexion à la base de données
            conn = get_db_connection()
            plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
            
            if not plan:
                flash('Plan Cadre non trouvé.', 'danger')
                conn.close()
                return redirect(url_for('main.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))
            
            # Récupérer le nom du cours pour les prompts
            cours = conn.execute('SELECT nom FROM Cours WHERE id = ?', (plan['cours_id'],)).fetchone()
            cours_nom = cours['nom'] if cours else "Non défini"

            parametres_generation = conn.execute('SELECT section, use_ai, text_content FROM GlobalGenerationSettings').fetchall()

            # Transformer la liste de tuples en dictionnaire
            parametres_dict = {section: {'use_ai': use_ai, 'text_content': text_content}
                               for section, use_ai, text_content in parametres_generation}

            plan_cadre_data = get_plan_cadre_data(plan['cours_id'])

            fields = [
                'Intro et place du cours',
                'Objectif terminal',
                'Introduction Structure du Cours',
                'Activités Théoriques',
                'Activités Pratiques',
                'Activités Prévues',
                'Évaluation Sommative des Apprentissages',
                'Nature des Évaluations Sommatives',
                'Évaluation de la Langue',
                'Évaluation formative des apprentissages',
            ]

            # (Optional) Define a mapping from field keys to database column names
            # If the keys match the column names, you can skip this mapping
            field_to_column = {
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

            # Initialize a dictionary to collect prompts where use_ai is enabled
            prompts = {}

            # Iterate over each field and apply the replacement and update logic
            for field in fields:
                # Retrieve the text content for the current field
                text_with_tags = parametres_dict[field]['text_content']
                
                # Replace Jinja2 tags with actual data
                replaced_text = replace_tags_jinja2(text_with_tags, plan_cadre_data)
                
                # Check if AI is not used for this field
                if parametres_dict[field]['use_ai'] == 0:
                    # Get the corresponding column name from the mapping
                    column_name = field_to_column.get(field)
                    
                    if column_name:
                        # Update the specific column in the PlanCadre table
                        conn.execute(f'''
                            UPDATE PlanCadre
                            SET {column_name} = ?
                            WHERE id = ?
                        ''', (replaced_text, plan_id))
                    else:
                        # Handle cases where the field is not mapped to any column
                        raise ValueError(f"No column mapping found for field: {field}")
                else:
                    # Collect the prompt for fields where AI is used
                    prompts[field] = replaced_text

            cursor = conn.cursor()

            if parametres_dict['Description des compétences développées']['use_ai'] == 1:
                cursor.execute("""
                    SELECT DISTINCT 
                        EC.competence_id,
                        C.nom AS competence_nom,
                        C.criteria_de_performance AS critere_performance,
                        C.contexte_de_realisation AS contexte_realisation
                    FROM 
                        ElementCompetence AS EC
                    JOIN 
                        ElementCompetenceParCours AS ECCP ON EC.id = ECCP.element_competence_id
                    JOIN 
                        Competence AS C ON EC.competence_id = C.id
                    WHERE 
                        ECCP.cours_id = ? AND ECCP.status = 'Développé significativement'
                """, (plan['cours_id'],))
                competences_developpees = cursor.fetchall()

                description_list = []
                description_prompts = {}

                role = f"Tu es un rédacteur de contenu pour un plan-cadre pour le cours '{plan_cadre_data['cours']['nom']}' situé en session {plan_cadre_data['cours'].get('session', 'Non défini')} sur 6 du programme {plan_cadre_data['programme']}"

                for competence in competences_developpees:
                    competence_id = competence['competence_id']
                    competence_nom = competence['competence_nom']
                    critere_performance = competence['critere_performance']
                    contexte_realisation = competence['contexte_realisation']

                    # Récupérer le texte avec les tags depuis les paramètres de génération
                    text_with_tags = parametres_dict['Description des compétences développées']['text_content']
                    
                    # Créer un dictionnaire de contexte pour remplacer les tags spécifiques à la compétence
                    extra_context = {
                        'competence_nom': competence_nom,
                        'critere_performance': critere_performance,
                        'contexte_realisation': contexte_realisation
                    }
                    
                    # Remplacer les tags dans le texte en utilisant le contexte combiné
                    replaced_text = replace_tags_jinja2(text_with_tags, plan_cadre_data, extra_context)

                    ai_description = process_ai_prompt(replaced_text, role)

                    # Insérer la description dans la table dédiée
                    cursor.execute("""
                        INSERT OR REPLACE INTO PlanCadreCompetencesDeveloppees (plan_cadre_id, texte, description)
                        VALUES (?, ?, ?);
                    """, (plan_id, competence_nom, ai_description))



                #for competence_id, competence_nom, critere_performance, contexte_realisation in competences_developpees:
                #    text_with_tags = parametres_dict['Description des compétences développées']['text_content']
                #    replaced_text = replace_tags_jinja2(text_with_tags, competences_developpees)
                #    prompts['Description des compétences développées'] = 



                    #cursor.execute("""
                    #    INSERT INTO PlanCadreCompetencesDeveloppees (plan_cadre_id, texte, description)
                    #    VALUES (?, ?, ?);
                    #""", (plan_id, competence_nom, 'Description of the new competence'))



            if prompts:
                logger.info("Envoi des prompts pour le traitement AI.")
                role = f"Tu es un rédacteur de contenu pour un plan-cadre pour le cours '{plan_cadre_data['cours']['nom']}' situé en session {plan_cadre_data['cours'].get('session', 'Non défini')} sur 6 du programme {plan_cadre_data['programme']}"

                updates = {}
                for field, prompt in prompts.items():
                    try:
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": role},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.7,
                            max_tokens=500
                        )
                        # Récupérer le contenu généré
                        generated_text = response.choices[0].message.content.strip()
                        updates[field] = generated_text
                        logger.info(f"Texte généré pour le champ '{field}'.")
                    except Exception as e:
                        logger.error(f"Erreur lors de l'appel à l'API OpenAI pour le champ '{field}': {e}")

                cursor = conn.cursor()
                def clean_generated_text(text):
                    return text.strip().strip('"').strip("'")

                # Mettre à jour la base de données avec les textes générés
                for field, generated_text in updates.items():
                    cleaned_text = clean_generated_text(generated_text)  # Supprime les guillemets
                    column_name = field_to_column.get(field)
                    if column_name:
                        logger.info(f"Mise à jour de la colonne '{column_name}' avec le texte généré pour le champ '{field}'.")
                        cursor.execute(f'''
                            UPDATE PlanCadre
                            SET {column_name} = ?
                            WHERE id = ?
                        ''', (cleaned_text, plan_id))
                    else:
                        logger.warning(f"Aucune correspondance de colonne pour le champ '{field}' lors de la mise à jour.")

            conn.commit()
            conn.close()

            flash('Contenu généré automatiquement avec succès!', 'success')
            return redirect(url_for('main.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))
        
        except Exception as e:
            flash(f'Erreur lors de la génération du contenu: {e}', 'danger')
            return redirect(url_for('main.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))
    else:
        flash('Erreur de validation du formulaire.', 'danger')
        return redirect(url_for('main.view_plan_cadre', plan_id=plan_id))

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
@login_required
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
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de la mise à jour du Plan Cadre : {e}', 'danger')
        finally:
            conn.close()
    
    conn.close()
    return render_template('edit_plan_cadre.html', form=form, plan_id=plan_id, plan=plan)

# Route pour supprimer un Plan Cadre
@plan_cadre_bp.route('/<int:plan_id>/delete', methods=['POST'])
@login_required
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
        
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        return redirect(url_for('main.index'))

# Route pour dupliquer un Plan Cadre
@plan_cadre_bp.route('/<int:plan_id>/duplicate', methods=['GET', 'POST'])
@login_required
def duplicate_plan_cadre(plan_id):
    form = DuplicatePlanCadreForm()
    conn = get_db_connection()
    
    # Récupérer le plan à dupliquer
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))
    
    # Récupérer les cours pour le choix de duplication (exclure le cours actuel)
    cours_options = conn.execute('SELECT id, nom FROM Cours WHERE id != ?', (plan['cours_id'],)).fetchall()
    form.new_cours_id.choices = [(c['id'], c['nom']) for c in cours_options]
    
    if form.validate_on_submit():
        new_cours_id = form.new_cours_id.data
        
        # Vérifier qu'un Plan Cadre n'existe pas déjà pour le nouveau cours
        existing_plan = conn.execute('SELECT * FROM PlanCadre WHERE cours_id = ?', (new_cours_id,)).fetchone()
        if existing_plan:
            flash('Un Plan Cadre existe déjà pour le cours sélectionné.', 'danger')
            conn.close()
            return redirect(url_for('main.duplicate_plan_cadre', plan_id=plan_id))
        
        try:
            # Copier les données principales
            conn.execute("""
                INSERT INTO PlanCadre 
                (cours_id, place_intro, objectif_terminal, structure_intro, structure_activites_theoriques, 
                structure_activites_pratiques, structure_activites_prevues, eval_evaluation_sommative, 
                eval_nature_evaluations_sommatives, eval_evaluation_de_la_langue, eval_evaluation_sommatives_apprentissages)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_cours_id, plan['place_intro'], plan['objectif_terminal'], plan['structure_intro'], 
                plan['structure_activites_theoriques'], plan['structure_activites_pratiques'], 
                plan['structure_activites_prevues'], plan['eval_evaluation_sommative'], 
                plan['eval_nature_evaluations_sommatives'], plan['eval_evaluation_de_la_langue'], 
                plan['eval_evaluation_sommatives_apprentissages']
            ))
            new_plan_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            
            # Copier les compétences développées
            competences = conn.execute('SELECT * FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for comp in competences:
                conn.execute("""
                    INSERT INTO PlanCadreCompetencesDeveloppees 
                    (plan_cadre_id, texte) VALUES (?, ?)
                """, (new_plan_id, comp['texte']))
            
            # Copier les objets cibles
            objets = conn.execute('SELECT * FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for obj in objets:
                conn.execute("""
                    INSERT INTO PlanCadreObjetsCibles 
                    (plan_cadre_id, texte) VALUES (?, ?)
                """, (new_plan_id, obj['texte']))
            
            # Copier les cours reliés
            cours_relies = conn.execute('SELECT * FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for cr in cours_relies:
                conn.execute("""
                    INSERT INTO PlanCadreCoursRelies 
                    (plan_cadre_id, texte) VALUES (?, ?)
                """, (new_plan_id, cr['texte']))
            
            # Copier les cours préalables
            cours_prealables = conn.execute('SELECT * FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for cp in cours_prealables:
                conn.execute("""
                    INSERT INTO PlanCadreCoursPrealables 
                    (plan_cadre_id, texte) VALUES (?, ?)
                """, (new_plan_id, cp['texte']))
            
            # Copier les capacités
            capacites = conn.execute('SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for cap in capacites:
                conn.execute("""
                    INSERT INTO PlanCadreCapacites 
                    (plan_cadre_id, capacite, description_capacite, ponderation_min, ponderation_max)
                    VALUES (?, ?, ?, ?, ?)
                """, (new_plan_id, cap['capacite'], cap['description_capacite'], cap['ponderation_min'], cap['ponderation_max']))
                new_cap_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                
                # Copier les savoirs nécessaires
                sav_necessaires = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', (cap['id'],)).fetchall()
                for sav in sav_necessaires:
                    conn.execute("""
                        INSERT INTO PlanCadreCapaciteSavoirsNecessaires 
                        (capacite_id, texte, cible, seuil_reussite) 
                        VALUES (?, ?, ?, ?)
                    """, (new_cap_id, sav['texte'], sav['cible'], sav['seuil_reussite']))
                
                # Copier les savoirs faire
                sav_faire = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', (cap['id'],)).fetchall()
                for sf in sav_faire:
                    conn.execute("""
                        INSERT INTO PlanCadreCapaciteSavoirsFaire 
                        (capacite_id, texte, cible, seuil_reussite) 
                        VALUES (?, ?, ?, ?)
                    """, (new_cap_id, sf['texte'], sf['cible'], sf['seuil_reussite']))
                
                # Copier les moyens d'évaluation
                moyens_eval = conn.execute('SELECT * FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', (cap['id'],)).fetchall()
                for me in moyens_eval:
                    conn.execute("""
                        INSERT INTO PlanCadreCapaciteMoyensEvaluation 
                        (capacite_id, texte) VALUES (?, ?)
                    """, (new_cap_id, me['texte']))
            
            # Copier le savoir-être
            savoir_etre = conn.execute('SELECT * FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
            for se in savoir_etre:
                conn.execute("""
                    INSERT INTO PlanCadreSavoirEtre 
                    (plan_cadre_id, texte) VALUES (?, ?)
                """, (new_plan_id, se['texte']))
            
            conn.commit()
            flash('Plan Cadre dupliqué avec succès!', 'success')
            return redirect(url_for('main.view_cours', cours_id=new_cours_id))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de la duplication du Plan Cadre : {e}', 'danger')
        finally:
            conn.close()

# Route pour ajouter une capacité au Plan Cadre
@plan_cadre_bp.route('/<int:plan_id>/add_capacite', methods=['GET', 'POST'])
@login_required
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
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
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
@login_required
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
        return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.', 'danger')
        # Il faut aussi rediriger correctement ici
        conn = get_db_connection()
        plan = conn.execute('SELECT cours_id FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
        conn.close()
        if plan:
            return redirect(url_for('main.view_plan_cadre', cours_id=plan['cours_id'], plan_id=plan_id))
        else:
            return redirect(url_for('main.index'))


# Route pour dupliquer une capacité (optionnel)
@plan_cadre_bp.route('/<int:plan_id>/capacite/<int:capacite_id>/duplicate', methods=['GET', 'POST'])
@login_required
def duplicate_capacite(plan_id, capacite_id):
    # Implémenter la duplication de la capacité si nécessaire
    pass