# populate_db.py
import sqlite3
import json
import os

def get_programme_id(conn, programme_name):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM Programme WHERE nom = ?;
    """, (programme_name,))
    result = cursor.fetchone()
    if result:
        programme_id = result[0]
        print(f"Programme '{programme_name}' trouvé avec l'ID {programme_id}.")
        return programme_id
    else:
        return None

def insert_programme(conn, programme_name):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Programme (nom) VALUES (?);
    """, (programme_name,))
    conn.commit()
    programme_id = cursor.lastrowid
    print(f"Programme '{programme_name}' inséré avec l'ID {programme_id}.")
    return programme_id

def insert_courses(conn, programme_id, courses):
    cursor = conn.cursor()
    course_code_to_id = {}
    
    for course in courses:
        # Vérifier si le cours existe déjà
        cursor.execute("""
            SELECT id FROM Cours WHERE code = ?;
        """, (course['code'],))
        result = cursor.fetchone()
        
        if result:
            course_id = result[0]
            print(f"Cours '{course['titre']}' avec le code '{course['code']}' existe déjà avec l'ID {course_id}.")
        else:
            # Parsing pondération (ex: "2-3-2") into heures_theorie, heures_laboratoire, heures_travail_maison
            pondération = course.get("pondération", "0-0-0")
            try:
                heures_theorie, heures_laboratoire, heures_travail_maison = map(int, pondération.split('-'))
            except ValueError:
                heures_theorie, heures_laboratoire, heures_travail_maison = 0, 0, 0
                print(f"Erreur de parsing pondération pour le cours {course['code']}. Valeurs par défaut utilisées.")
            
            # Nombre d'unités: Si vous avez une logique pour le déterminer, appliquez-la ici.
            # Sinon, vous pouvez définir une valeur par défaut ou ajouter un champ dans le JSON.
            nombre_unites = 0  # Modifier si nécessaire
            
            cursor.execute("""
                INSERT INTO Cours (programme_id, code, nom, nombre_unites, session, heures_theorie, heures_laboratoire, heures_travail_maison)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                programme_id,
                course['code'],
                course['titre'],
                nombre_unites,
                course['session'],
                heures_theorie,
                heures_laboratoire,
                heures_travail_maison
            ))
            conn.commit()
            course_id = cursor.lastrowid
            print(f"Cours '{course['titre']}' inséré avec l'ID {course_id}.")
        
        course_code_to_id[course['code']] = course_id
    
    return course_code_to_id

def insert_element_competence_par_cours(conn, competencies, course_code_to_id):
    cursor = conn.cursor()
    
    for comp in competencies:
        comp_code = comp['code']
        for sub_comp in comp['subCompetencies']:
            sub_comp_id = sub_comp['id']
            sub_comp_description = sub_comp['description']
            for course in sub_comp['courses']:
                course_code = course['code']
                status = course['status']
                
                # Normaliser le statut
                status_normalized = status.strip().capitalize()
                if status_normalized.lower() == "traités significativement":
                    status_normalized = "Développé significativement"
                
                # Obtenir l'ID du cours
                cours_id = course_code_to_id.get(course_code)
                if not cours_id:
                    print(f"Erreur: Cours avec le code '{course_code}' non trouvé pour la sous-compétence '{sub_comp_description}'.")
                    continue
                
                # Obtenir l'ID de l'ElementCompetence basé sur la compétence et la description de la sous-compétence
                cursor.execute("""
                    SELECT ec.id
                    FROM ElementCompetence ec
                    JOIN Competence c ON ec.competence_id = c.id
                    WHERE c.code = ? AND ec.nom = ?;
                """, (comp_code, sub_comp_description))
                result = cursor.fetchone()
                if not result:
                    print(f"Erreur: ElementCompetence pour la compétence '{comp_code}' et la sous-compétence '{sub_comp_description}' non trouvé.")
                    continue
                element_competence_id = result[0]
                
                # Vérifier si la liaison existe déjà
                cursor.execute("""
                    SELECT id FROM ElementCompetenceParCours
                    WHERE cours_id = ? AND element_competence_id = ?;
                """, (cours_id, element_competence_id))
                existing = cursor.fetchone()
                if existing:
                    print(f"Liaison entre Cours ID {cours_id} et ElementCompetence ID {element_competence_id} existe déjà.")
                    continue
                
                # Insérer la liaison
                cursor.execute("""
                    INSERT INTO ElementCompetenceParCours (cours_id, element_competence_id, status)
                    VALUES (?, ?, ?);
                """, (
                    cours_id,
                    element_competence_id,
                    status_normalized
                ))
                conn.commit()
                print(f"Liaison Cours ID {cours_id} avec ElementCompetence ID {element_competence_id} insérée avec le statut '{status_normalized}'.")
                
def insert_prealables_corequis(conn, courses, course_code_to_id):
    cursor = conn.cursor()
    
    for course in courses:
        cours_id = course_code_to_id.get(course['code'])
        if not cours_id:
            print(f"Erreur: Cours '{course['code']}' non trouvé pour les préalables/corequis.")
            continue
        
        # Insertion des préalables
        for pre in course.get('préalables', []):
            pre_code = pre['code']
            pre_type = pre.get('type', '').lower()  # 'relatif' ou 'absolu'
            
            # Déterminer la note nécessaire basée sur le type
            if pre_type == 'relatif':
                note_necessaire = 50
            elif pre_type == 'absolu':
                note_necessaire = 60
            else:
                note_necessaire = None
                print(f"Type de préalable inconnu pour le cours '{course['code']}' et le préalable '{pre_code}'.")
            
            pre_id = course_code_to_id.get(pre_code)
            if pre_id:
                # Vérifier si la liaison existe déjà
                cursor.execute("""
                    SELECT id FROM CoursPrealable
                    WHERE cours_id = ? AND cours_prealable_id = ?;
                """, (cours_id, pre_id))
                existing = cursor.fetchone()
                if existing:
                    print(f"Péalable: Cours ID {cours_id} nécessite déjà le cours ID {pre_id}.")
                    continue
                
                cursor.execute("""
                    INSERT INTO CoursPrealable (cours_id, cours_prealable_id, note_necessaire)
                    VALUES (?, ?, ?);
                """, (
                    cours_id,
                    pre_id,
                    note_necessaire
                ))
                conn.commit()
                print(f"Péalable: Cours ID {cours_id} nécessite le cours ID {pre_id} avec une note nécessaire de {note_necessaire}%.")
            else:
                print(f"Erreur: Péalable '{pre_code}' non trouvé pour le cours '{course['code']}'.")
        
        # Insertion des corequis
        for co in course.get('corequis', []):
            co_code = co
            co_id = course_code_to_id.get(co_code)
            if co_id:
                # Vérifier si la liaison existe déjà
                cursor.execute("""
                    SELECT id FROM CoursCorequis
                    WHERE cours_id = ? AND cours_corequis_id = ?;
                """, (cours_id, co_id))
                existing = cursor.fetchone()
                if existing:
                    print(f"Corequis: Cours ID {cours_id} a déjà le corequis ID {co_id}.")
                    continue
                
                cursor.execute("""
                    INSERT INTO CoursCorequis (cours_id, cours_corequis_id)
                    VALUES (?, ?);
                """, (
                    cours_id,
                    co_id
                ))
                conn.commit()
                print(f"Corequis: Cours ID {cours_id} a le corequis ID {co_id}.")
            else:
                print(f"Erreur: Corequis '{co_code}' non trouvé pour le cours '{course['code']}'.")
    
def main():
    # Nom du fichier JSON
    json_filename = 'data_cours.json'
    
    # Vérifier si le fichier JSON existe
    if not os.path.exists(json_filename):
        print(f"Erreur: Le fichier '{json_filename}' n'a pas été trouvé dans le répertoire actuel.")
        return
    
    # Charger les données JSON
    with open(json_filename, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            print(f"Fichier '{json_filename}' chargé avec succès.")
        except json.JSONDecodeError as e:
            print(f"Erreur de décodage JSON: {e}")
            return
    
    # Connexion à la base de données
    conn = sqlite3.connect('programme.db')
    
    try:
        # Définir le nom exact du programme
        programme_nom = "Technologie du génie électrique : Réseaux et télécommunications (243.F0)"
        
        # Démarrer une transaction
        conn.execute('BEGIN TRANSACTION;')
        
        # Vérifier si le programme existe déjà
        programme_id = get_programme_id(conn, programme_nom)
        if not programme_id:
            # Insérer le programme s'il n'existe pas
            programme_id = insert_programme(conn, programme_nom)
        else:
            print(f"Utilisation du programme existant avec l'ID {programme_id}.")
        
        # Insérer les cours
        courses = data.get('courses', [])
        if not courses:
            print("Aucun cours trouvé dans le fichier JSON.")
            conn.rollback()
            return
        course_code_to_id = insert_courses(conn, programme_id, courses)
        
        # Insérer les relations ElementCompetenceParCours
        competencies = data.get('competencies', [])
        if competencies:
            insert_element_competence_par_cours(conn, competencies, course_code_to_id)
        else:
            print("Aucune compétence trouvée dans le fichier JSON pour lier les cours.")
        
        # Insérer les préalables et corequis
        insert_prealables_corequis(conn, courses, course_code_to_id)
        
        # Commit de la transaction
        conn.commit()
        print("Toutes les données ont été insérées avec succès.")
    
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"Erreur d'intégrité de la base de données: {e}")
    
    except Exception as e:
        conn.rollback()
        print(f"Une erreur s'est produite: {e}")
    
    finally:
        conn.close()

if __name__ == "__main__":
    main()
