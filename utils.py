import os
import sqlite3
from jinja2 import Template
from bs4 import BeautifulSoup
from docxtpl import DocxTemplate
from io import BytesIO
import os
from dotenv import load_dotenv

DATABASE = 'programme.db'

def get_initials(nom_complet):
    """
    Extrait les initiales d'un nom complet.
    
    Args:
        nom_complet (str): Le nom complet de l'enseignant
        
    Returns:
        str: Les initiales en majuscules
    """
    # Supprimer les espaces superflus et séparer les mots
    mots = nom_complet.strip().split()
    
    # Obtenir la première lettre de chaque mot et la convertir en majuscule
    initiales = ''.join(mot[0].upper() for mot in mots if mot)
    
    return initiales

    
def get_all_cegeps():
    conn = get_db_connection()
    cegeps = conn.execute('SELECT id, nom FROM ListeCegep').fetchall()
    conn.close()
    return cegeps

def get_cegep_details_data(cegep_id):
    conn = get_db_connection()
    departments = conn.execute('SELECT id, nom FROM Department WHERE cegep_id = ?', (cegep_id,)).fetchall()
    programmes = conn.execute('SELECT id, nom FROM Programme WHERE cegep_id = ?', (cegep_id,)).fetchall()
    conn.close()

    return {
        'departments': [{'id': d['id'], 'nom': d['nom']} for d in departments],
        'programmes': [{'id': p['id'], 'nom': p['nom']} for p in programmes]
    }



def get_all_departments():
    conn = get_db_connection()
    departments = conn.execute('SELECT id, nom FROM Department').fetchall()
    conn.close()
    return departments

def get_all_programmes():
    conn = get_db_connection()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()
    return programmes

def get_programmes_by_user(user_id):
    conn = get_db_connection()
    programmes = conn.execute('SELECT programme_id FROM User_Programme WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    return programmes


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Permet de récupérer les résultats sous forme de dictionnaire
    return conn

def parse_html_to_list(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    return [li.get_text(strip=True) for li in soup.find_all('li')]

def parse_html_to_nested_list(html_content):
    """
    Parses HTML content with nested <ul> and <ol> elements and returns a
    nested list structure with sub-items included recursively.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    def process_list(items):
        result = []
        for li in items:
            # Main text for the <li>
            item_text = li.contents[0].strip() if li.contents else ""
            sub_items = []

            # Look for nested <ul> or <ol> within the current <li>
            nested_list = li.find('ul') or li.find('ol')
            if nested_list:
                sub_items = process_list(nested_list.find_all('li', recursive=False))

            # Append main item and its sub-items
            if sub_items:
                result.append({
                    'text': item_text,
                    'sub_items': sub_items
                })
            else:
                result.append({
                    'text': item_text
                })
        return result

    # Start processing from the top-level <ul> or <ol>
    top_list = soup.find('ul') or soup.find('ol')
    if top_list:
        return process_list(top_list.find_all('li', recursive=False))
    else:
        return []  # Return an empty list if no <ul> or <ol> is found

def get_plan_cadre_data(cours_id, db_path='programme.db'):
    """
    Récupère et retourne les informations d'un plan cadre pour un cours donné sous format JSON.
    
    :param cours_id: ID du cours dans la table Cours.
    :param db_path: Chemin vers la base de données SQLite.
    :return: Données structurées sous forme de dictionnaire
    """
    plan_cadre = {}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Nom du cours, Code du cours et session
        cursor.execute(""" 
            SELECT nom, code, fil_conducteur_id, session, programme_id, heures_theorie, heures_laboratoire, heures_travail_maison
            FROM Cours
            WHERE id = ?
        """, (cours_id,))
        cours = cursor.fetchone()
        if not cours:
            print(f"Aucun cours trouvé avec l'ID {cours_id}.")
            return None
        nom_cours, code_cours, fil_conducteur_id, session, programme_id, heures_theorie, heures_laboratoire, heures_travail_maison = cours
        plan_cadre['cours'] = {
            'nom': nom_cours,
            'code': code_cours,
            'session': session,
            'heures_theorie': heures_theorie,
            'heures_laboratoire': heures_laboratoire,
            'heures_maison': heures_travail_maison
        }

        # 2. Nom du programme
        if programme_id:
            cursor.execute("""
                SELECT nom
                FROM Programme
                WHERE id = ?
            """, (programme_id,))
            programme = cursor.fetchone()
            programme_nom = programme[0] if programme else "Non défini"
        else:
            programme_nom = "Non défini"
        plan_cadre['programme'] = programme_nom

        # 2. Fil conducteur
        if fil_conducteur_id:
            cursor.execute("""
                SELECT description
                FROM FilConducteur
                WHERE id = ?
            """, (fil_conducteur_id,))
            fil_conducteur = cursor.fetchone()
            fil_conducteur_desc = fil_conducteur[0] if fil_conducteur else "Non défini"
        else:
            fil_conducteur_desc = "Non défini"
        plan_cadre['fil_conducteur'] = fil_conducteur_desc

        # 3. Éléments de compétence développée ou atteinte
        cursor.execute("""
            SELECT 
                EC.id AS element_competence_id,
                EC.nom AS element_nom,
                ECCP.status AS status,
                EC.competence_id AS competence_id,
                ECC.criteria AS critere_performance
            FROM 
                ElementCompetence AS EC
            JOIN 
                ElementCompetenceParCours AS ECCP ON EC.id = ECCP.element_competence_id
            LEFT JOIN 
                ElementCompetenceCriteria AS ECC ON EC.id = ECC.element_competence_id
            WHERE 
                ECCP.cours_id = ?
        """, (cours_id,))
        element_competences_developpees = cursor.fetchall()
        plan_cadre['elements_competences_developpees'] = []
        for element_competence_id, element_nom, status, competence_id, critere_performance in element_competences_developpees:
            plan_cadre['elements_competences_developpees'].append({
                'element_nom': element_nom,
                'element_competence_id': element_competence_id,
                'status': status,
                'competence_id': competence_id,
                'critere_performance': critere_performance
            })

        # 4. Compétences développées
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
        """, (cours_id,))
        competences_developpees = cursor.fetchall()
        plan_cadre['competences_developpees'] = []
        for competence_id, competence_nom, critere_performance, contexte_realisation in competences_developpees:
            plan_cadre['competences_developpees'].append({
                'competence_nom': competence_nom,
                'competence_id': competence_id,
                'critere_performance': critere_performance,
                'contexte_realisation': contexte_realisation
            })

        # 5. Compétences atteintes
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
                ECCP.cours_id = ? AND ECCP.status = 'Atteint'
        """, (cours_id,))
        competences_atteintes = cursor.fetchall()
        plan_cadre['competences_atteintes'] = []
        for competence_id, competence_nom, critere_performance, contexte_realisation in competences_atteintes:
            plan_cadre['competences_atteintes'].append({
                'competence_nom': competence_nom,
                'competence_id': competence_id,
                'critere_performance': critere_performance,
                'contexte_realisation': contexte_realisation
            })

        # 6. Cours préalables
        cursor.execute("""
            SELECT 
                CP.cours_prealable_id,
                CP2.nom AS cours_prealable_nom,
                CP2.code AS cours_prealable_code
            FROM 
                Cours AS C
            JOIN 
                CoursPrealable AS CP ON C.id = CP.cours_id
            JOIN 
                Cours AS CP2 ON CP.cours_prealable_id = CP2.id
            WHERE 
                C.id = ?
        """, (cours_id,))
        prealables = cursor.fetchall()
        plan_cadre['cours_prealables'] = []
        for preal_id, preal_nom, preal_code in prealables:
            plan_cadre['cours_prealables'].append({
                'cours_prealable_code': preal_code,
                'cours_prealable_nom': preal_nom,
                'cours_prealable_id': preal_id
            })

        # 7. Préalable à quel(s) cours
        cursor.execute("""
            SELECT 
                CP.cours_id AS cours_prealable_a_id,
                CP2.nom AS cours_prealable_a_nom,
                CP2.code AS cours_prealable_a_code
            FROM 
                Cours AS C
            JOIN 
                CoursPrealable AS CP ON C.id = CP.cours_prealable_id
            JOIN 
                Cours AS CP2 ON CP.cours_id = CP2.id
            WHERE 
                C.id = ?
        """, (cours_id,))
        prealables_of = cursor.fetchall()
        plan_cadre['prealables_of'] = []
        for cours_id_rel, cours_nom_rel, cours_code_rel in prealables_of:
            plan_cadre['prealables_of'].append({
                'cours_prealable_a_code': cours_code_rel,
                'cours_prealable_a_nom': cours_nom_rel,
                'cours_prealable_a_id': cours_id_rel
            })

        # 8. Cours corequis
        cursor.execute("""
            SELECT CoursCorequis.cours_corequis_id, Cours.nom
            FROM CoursCorequis
            JOIN Cours ON CoursCorequis.cours_corequis_id = Cours.id
            WHERE CoursCorequis.cours_id = ?
        """, (cours_id,))
        corequis = cursor.fetchall()
        plan_cadre['cours_corequis'] = []
        for coreq_id, coreq_nom in corequis:
            plan_cadre['cours_corequis'].append({
                'cours_corequis_id': coreq_id,
                'cours_corequis_nom': coreq_nom
            })

        # 9. Cours développant une même compétence avant, pendant et après
        cursor.execute("""
            SELECT 
                C.id AS cours_id,
                C.nom AS cours_nom,
                C.code AS code,
                C.session AS session,
                GROUP_CONCAT(DISTINCT EC.competence_id) AS competence_ids
            FROM
                Cours AS C
            JOIN
                ElementCompetenceParCours AS ECCP ON C.id = ECCP.cours_id
            JOIN
                ElementCompetence AS EC ON ECCP.element_competence_id = EC.id
            WHERE
                EC.id IN (
                    SELECT element_competence_id
                    FROM ElementCompetenceParCours
                    WHERE cours_id = ?
                )
                AND C.id != ?
            GROUP BY
                C.id, C.nom, C.code, C.session;
        """, (cours_id, cours_id))
        corequis = cursor.fetchall()
        plan_cadre['cours_developpant_une_meme_competence'] = []
        for cours_id, cours_nom, code, session, competence_ids in corequis:
            plan_cadre['cours_developpant_une_meme_competence'].append({
                'cours_nom': cours_nom,
                'cours_id': cours_id,
                'code': code,
                'session': session,
                'competence_ids': competence_ids
            })

    except sqlite3.Error as e:
        print(f"Erreur SQLite: {e}")
        return None
    finally:
        if conn:
            conn.close()

    return plan_cadre

def replace_tags_jinja2(text, plan_cadre, extra_context=None):
    """
    Utilise Jinja2 pour remplacer les tags dans le texte avec les données de plan_cadre et un contexte supplémentaire.
    
    :param text: Le texte contenant des tags Jinja2.
    :param plan_cadre: Le dictionnaire contenant les données du plan cadre.
    :param extra_context: Un dictionnaire supplémentaire pour remplacer ou ajouter des variables.
    :return: Le texte avec les tags remplacés.
    """
    try:
        template = Template(text)
        
        # Préparer le contexte de remplacement
        context = {
            'code_cours': plan_cadre['cours']['code'],
            'nom_cours': plan_cadre['cours']['nom'],
            'fil_conducteur': plan_cadre['fil_conducteur'],
            'programme': plan_cadre['programme'],
            'session': plan_cadre['cours'].get('session', 'Non défini'),
            'competences_developpees': plan_cadre.get('competences_developpees', []),
            'competences_atteintes': plan_cadre.get('competences_atteintes', []),
            'cours_prealables': plan_cadre.get('cours_prealables', []),
            'cours_corequis': plan_cadre.get('cours_corequis', []),
            'cours_developpant_une_meme_competence': plan_cadre.get('cours_developpant_une_meme_competence', []),
            'heures_theorie': plan_cadre['cours']['heures_theorie'],
            'heures_lab': plan_cadre['cours']['heures_laboratoire'],
            'heures_maison': plan_cadre['cours']['heures_maison']
        }
        
        # Ajouter le contexte supplémentaire si fourni
        if extra_context:
            context.update(extra_context)

        #print(context['competence_nom'])
        
        # Rendre le template avec le contexte
        replaced_text = template.render(**context)
        return replaced_text
    except KeyError as e:
        print("Clé manquante dans le contexte lors du rendu du template")
        raise
    except Exception as e:
        print("Erreur lors du rendu du template Jinja2")
        raise

def process_ai_prompt(prompt, role):
    """
    Sends the prompt to the AI service and returns the generated content.
    """
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
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Log the exception
        print("Error generating AI content")
        return None

import os

def generate_docx_with_template(plan_id):
    # Connexion à la base de données
    conn = get_db_connection()

    template_path = os.path.join('static', 'docs', 'plan_cadre_template.docx')

    # Vérifier l'existence du modèle DOCX
    if not os.path.exists(template_path):
        print("Erreur : Le modèle DOCX n'a pas été trouvé !")
        conn.close()
        return None

    # Récupérer les informations du plan cadre
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
    if not plan:
        conn.close()
        return None

    # Récupérer les informations du cours associé
    cours = conn.execute('SELECT * FROM Cours WHERE id = ?', (plan['cours_id'],)).fetchone()
    if not cours:
        conn.close()
        return None

    # Récupérer les informations du programme associé au cours
    programme = conn.execute('''
        SELECT Programme.nom AS programme_nom, Department.nom AS department_nom
        FROM Programme
        JOIN Department ON Programme.department_id = Department.id
        WHERE Programme.id = ?
    ''', (cours['programme_id'],)).fetchone()

    # Récupérer les compétences développées avec leur texte et description
    competences_developpees = conn.execute('''
        SELECT texte, description
        FROM PlanCadreCompetencesDeveloppees
        WHERE plan_cadre_id = ?
    ''', (plan_id,)).fetchall()

    # Récupérer les données de la base de données pour les compétences développées
    element_competences_par_cours = conn.execute('SELECT element_competence_id, status FROM ElementCompetenceParCours WHERE cours_id = ?', (cours['id'],)).fetchall()

    # Créer un ensemble pour stocker les IDs uniques des compétences développées
    competence_ids = set()
    for element in element_competences_par_cours:
        if element[1] == 'Développé significativement':
            competence_ids.add(element[0])

    competence_ids_uniques = list(competence_ids)
    competence_ids = set()

    # Récupérer les IDs des compétences pour les éléments de compétence
    for elemcompid in competence_ids_uniques:
        competence_cours = conn.execute('SELECT competence_id FROM ElementCompetence WHERE id = ?', (elemcompid,)).fetchall()
        for i in competence_cours:
            competence_ids.add(i[0])
    
    competence_ids_uniques = list(competence_ids)
    competence_info_developes = {}

    for elemcompid in competence_ids_uniques:
        cursor = conn.cursor()
        competence_cours = cursor.execute(
            'SELECT id, code, nom, criteria_de_performance, contexte_de_realisation FROM Competence WHERE id = ?',
            (elemcompid,)
        ).fetchall()

        columns = [column[0] for column in cursor.description]
        for row in competence_cours:
            row_dict = dict(zip(columns, row))

            contexte_html = row_dict['contexte_de_realisation']
            row_dict['contexte_de_realisation'] = parse_html_to_nested_list(contexte_html)

            criteria_html = row_dict['criteria_de_performance']
            row_dict['criteria_de_performance'] = parse_html_to_list(criteria_html)

            if row_dict['id'] not in competence_info_developes:
                competence_info_developes[row_dict['id']] = {
                    "id": row_dict['id'],
                    "code": row_dict['code'],
                    "nom": row_dict['nom'],
                    "criteria_de_performance": row_dict['criteria_de_performance'],
                    "contexte_de_realisation": row_dict['contexte_de_realisation'],
                    "elements": []
                }

            # Récupérer les éléments de compétence
            element_competence_data = cursor.execute("""
                SELECT 
                    ec.id AS element_competence_id, 
                    ec.nom, 
                    ec.competence_id
                FROM 
                    ElementCompetence AS ec
                WHERE 
                    ec.competence_id = ?
            """, (row_dict['id'],)).fetchall()

            # Pour chaque élément de compétence, récupérer ses critères individuellement
            for row in element_competence_data:
                element_competence = {
                    "element_competence_id": row[0],
                    "nom": row[1],
                    "competence_id": row[2],
                    "criteria": []
                }
                
                # Récupérer les critères individuellement
                criteria_data = cursor.execute("""
                    SELECT criteria
                    FROM ElementCompetenceCriteria
                    WHERE element_competence_id = ?
                """, (row[0],)).fetchall()
                
                # Ajouter chaque critère à la liste
                element_competence["criteria"] = [criterion[0] for criterion in criteria_data]
                
                competence_info_developes[row_dict['id']]["elements"].append(element_competence)

    # Ajouter les informations sur les cours associés
    for competence in competence_info_developes.values():
        for element in competence["elements"]:
            element_competence_id = element["element_competence_id"]

            if "cours_associes" not in element:
                element["cours_associes"] = []

            cursor.execute("""
                SELECT 
                    c.id AS cours_id,
                    c.code AS cours_code,
                    c.nom AS cours_nom,
                    c.session AS cours_session,
                    ecpc.status AS element_competence_status
                FROM 
                    Cours AS c
                JOIN 
                    ElementCompetenceParCours AS ecpc ON c.id = ecpc.cours_id
                WHERE 
                    ecpc.element_competence_id = ?
                ORDER BY 
                    c.session;
            """, (element_competence_id,))

            element["cours_associes"].extend([
                {
                    "cours_id": row[0],
                    "cours_code": row[1],
                    "cours_nom": row[2],
                    "cours_session": row[3],
                    "status": row[4]
                }
                for row in cursor.fetchall()
            ])

    # Répéter le même processus pour les compétences atteintes
    competence_ids = set()
    element_competences_par_cours = conn.execute('SELECT element_competence_id, status FROM ElementCompetenceParCours WHERE cours_id = ?', (cours['id'],)).fetchall()
    
    for element in element_competences_par_cours:
        if element[1] == 'Atteint':
            competence_ids.add(element[0])

    competence_ids_uniques = list(competence_ids)
    competence_ids = set()

    for elemcompid in competence_ids_uniques:
        competence_cours = conn.execute('SELECT competence_id FROM ElementCompetence WHERE id = ?', (elemcompid,)).fetchall()
        for i in competence_cours:
            competence_ids.add(i[0])
    
    competence_ids_uniques = list(competence_ids)
    competence_info_atteint = {}

    for elemcompid in competence_ids_uniques:
        cursor = conn.cursor()
        competence_cours = cursor.execute(
            'SELECT id, code, nom, criteria_de_performance, contexte_de_realisation FROM Competence WHERE id = ?',
            (elemcompid,)
        ).fetchall()

        columns = [column[0] for column in cursor.description]
        for row in competence_cours:
            row_dict = dict(zip(columns, row))

            contexte_html = row_dict['contexte_de_realisation']
            row_dict['contexte_de_realisation'] = parse_html_to_nested_list(contexte_html)

            criteria_html = row_dict['criteria_de_performance']
            row_dict['criteria_de_performance'] = parse_html_to_list(criteria_html)

            if row_dict['id'] not in competence_info_atteint:
                competence_info_atteint[row_dict['id']] = {
                    "id": row_dict['id'],
                    "code": row_dict['code'],
                    "nom": row_dict['nom'],
                    "criteria_de_performance": row_dict['criteria_de_performance'],
                    "contexte_de_realisation": row_dict['contexte_de_realisation'],
                    "elements": []
                }

            # Récupérer les éléments de compétence
            element_competence_data = cursor.execute("""
                SELECT 
                    ec.id AS element_competence_id, 
                    ec.nom, 
                    ec.competence_id
                FROM 
                    ElementCompetence AS ec
                WHERE 
                    ec.competence_id = ?
            """, (row_dict['id'],)).fetchall()

            # Pour chaque élément de compétence, récupérer ses critères individuellement
            for row in element_competence_data:
                element_competence = {
                    "element_competence_id": row[0],
                    "nom": row[1],
                    "competence_id": row[2],
                    "criteria": []
                }
                
                # Récupérer les critères individuellement
                criteria_data = cursor.execute("""
                    SELECT criteria
                    FROM ElementCompetenceCriteria
                    WHERE element_competence_id = ?
                """, (row[0],)).fetchall()
                
                # Ajouter chaque critère à la liste
                element_competence["criteria"] = [criterion[0] for criterion in criteria_data]
                
                competence_info_atteint[row_dict['id']]["elements"].append(element_competence)

    # Ajouter les informations sur les cours associés pour les compétences atteintes
    for competence in competence_info_atteint.values():
        for element in competence["elements"]:
            element_competence_id = element["element_competence_id"]

            if "cours_associes" not in element:
                element["cours_associes"] = []

            cursor.execute("""
                SELECT 
                    c.id AS cours_id,
                    c.code AS cours_code,
                    c.nom AS cours_nom,
                    c.session AS cours_session,
                    ecpc.status AS element_competence_status
                FROM 
                    Cours AS c
                JOIN 
                    ElementCompetenceParCours AS ecpc ON c.id = ecpc.cours_id
                WHERE 
                    ecpc.element_competence_id = ?
                ORDER BY 
                    c.session;
            """, (element_competence_id,))

            element["cours_associes"].extend([
                {
                    "cours_id": row[0],
                    "cours_code": row[1],
                    "cours_nom": row[2],
                    "cours_session": row[3],
                    "status": row[4]
                }
                for row in cursor.fetchall()
            ])

    # Récupérer les autres informations nécessaires
    objets_cibles = conn.execute('SELECT texte, description FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    cours_relies = conn.execute('SELECT texte, description FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    
    # Récupérer et structurer les capacités
    capacites = conn.execute('SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    capacites_detail = []
    for cap in capacites:
        cap_id = cap['id']
        sav_necessaires = conn.execute('SELECT texte FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', (cap_id,)).fetchall()
        sav_faire = conn.execute('SELECT texte, cible, seuil_reussite FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', (cap_id,)).fetchall()
        moyens_eval = conn.execute('SELECT texte FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', (cap_id,)).fetchall()

        capacites_detail.append({
            'capacite': cap['capacite'],
            'description_capacite': cap['description_capacite'],
            'ponderation_min': cap['ponderation_min'],
            'ponderation_max': cap['ponderation_max'],
            'savoirs_necessaires': [sav['texte'] for sav in sav_necessaires],
            'savoirs_faire': [
                {
                    'texte': sf['texte'],
                    'cible': sf['cible'],
                    'seuil_reussite': sf['seuil_reussite']
                } for sf in sav_faire
            ],
            'moyens_evaluation': [me['texte'] for me in moyens_eval]
        })

    savoir_etre = conn.execute('SELECT texte FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    cours_corequis = conn.execute('SELECT texte, description FROM PlanCadreCoursCorequis WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    competences_certifiees = conn.execute('SELECT texte, description FROM PlanCadreCompetencesCertifiees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()


    # 9. Cours développant une même compétence avant, pendant et après
    cours_meme_competence = conn.execute("""
        SELECT 
            C.id AS cours_id,
            C.nom AS cours_nom,
            C.code AS code,
            C.session AS session,
            GROUP_CONCAT(DISTINCT EC.competence_id) AS competence_ids
        FROM
            Cours AS C
        JOIN
            ElementCompetenceParCours AS ECCP ON C.id = ECCP.cours_id
        JOIN
            ElementCompetence AS EC ON ECCP.element_competence_id = EC.id
        WHERE
            EC.id IN (
                SELECT element_competence_id
                FROM ElementCompetenceParCours
                WHERE cours_id = ?
            )
        GROUP BY
            C.id, C.nom, C.code, C.session;
    """, (plan['cours_id'],)).fetchall() 

    # Récupérer les cours corequis avec leur nom et code
    cc = conn.execute('''
        SELECT DISTINCT C2.nom AS nom, C2.code AS code
        FROM CoursCorequis CC
        JOIN Cours C2 ON CC.cours_corequis_id = C2.id
        WHERE CC.cours_id = ?
    ''', (plan['cours_id'],)).fetchall()

    # Récupérer les cours préalables avec leur nom, code et note nécessaire
    cp = conn.execute('''
        SELECT DISTINCT C2.nom AS nom, C2.code AS code, CP.note_necessaire
        FROM CoursPrealable CP
        JOIN Cours C2 ON CP.cours_prealable_id = C2.id
        WHERE CP.cours_id = ?
    ''', (plan['cours_id'],)).fetchall()

    # Fermer la connexion
    conn.close()

    # Structurer les données dans un dictionnaire de contexte
    context = {
        'programme': {
            'nom': programme['programme_nom'] if programme else 'Non défini',
            'departement': programme['department_nom'] if programme else 'Non défini'
        },
        'cours': {
            'code': cours['code'],
            'nom': cours['nom'],
            'session': cours['session'],
            'heures_theorie': cours['heures_theorie'],
            'heures_laboratoire': cours['heures_laboratoire'],
            'heures_travail_maison': cours['heures_travail_maison'],
            'nombre_unites': cours['nombre_unites']
        },
        'plan_cadre': {
            'place_intro': plan['place_intro'],
            'objectif_terminal': plan['objectif_terminal'],
            'structure_intro': plan['structure_intro'],
            'structure_activites_theoriques': plan['structure_activites_theoriques'],
            'structure_activites_pratiques': plan['structure_activites_pratiques'],
            'structure_activites_prevues': plan['structure_activites_prevues'],
            'eval_evaluation_sommative': plan['eval_evaluation_sommative'],
            'eval_nature_evaluations_sommatives': plan['eval_nature_evaluations_sommatives'],
            'eval_evaluation_de_la_langue': plan['eval_evaluation_de_la_langue'],
            'eval_evaluation_sommatives_apprentissages': plan['eval_evaluation_sommatives_apprentissages']
        },
        'competences_developpees': [
            {'texte': cd['texte'], 'description': cd['description']} for cd in competences_developpees
        ],
        'objets_cibles': [dict(o) for o in objets_cibles],
        'cours_relies': [dict(cr) for cr in cours_relies],
        'capacites': capacites_detail,
        'savoir_etre': [dict(se) for se in savoir_etre],
        'competences_info_developes': [competence for competence in competence_info_developes.values()],
        'competences_info_atteint': [competence for competence in competence_info_atteint.values()],
        'cours_corequis': [dict(cro) for cro in cours_corequis],
        'competences_certifiees': [dict(cc) for cc in competences_certifiees],
        'cours_developpant_une_meme_competence': [dict(cdmc) for cdmc in cours_meme_competence],
        'cc': [
            {'nom': cc['nom'], 'code': cc['code']} 
            for cc in cc
        ],
        'cp': [
            {
                'nom': cp['nom'], 
                'code': cp['code'],
                'note_necessaire': cp['note_necessaire']
            } 
            for cp in cp
        ]
    }

    # Charger le modèle DOCX
    tpl = DocxTemplate(template_path)

    # Remplir le modèle avec les données
    tpl.render(context)

    # Sauvegarder le document dans un objet BytesIO
    file_stream = BytesIO()
    tpl.save(file_stream)
    file_stream.seek(0)

    return file_stream


def get_programme_id(conn, competence_id):
    """
    Fonction utilitaire pour récupérer le programme_id à partir d'une competence_id.
    """
    programme = conn.execute('SELECT programme_id FROM Competence WHERE id = ?', (competence_id,)).fetchone()
    return programme['programme_id'] if programme else None
