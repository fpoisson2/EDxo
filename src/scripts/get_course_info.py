import sqlite3
import json

def get_plan_cadre(cours_id, db_path='votre_base_de_donnees.db'):
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

        # 1. Nom du cours et Code du cours
        cursor.execute("""
            SELECT nom, code, fil_conducteur_id
            FROM Cours
            WHERE id = ?
        """, (cours_id,))
        cours = cursor.fetchone()
        if not cours:
            print(f"Aucun cours trouvé avec l'ID {cours_id}.")
            return None
        nom_cours, code_cours, fil_conducteur_id = cours
        plan_cadre['cours'] = {
            'nom': nom_cours,
            'code': code_cours
        }

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


# Exemple d'utilisation
if __name__ == "__main__":
    # Remplacez '1' par l'ID du cours souhaité et 'votre_base_de_donnees.db' par le chemin de votre base de données
    plan_cadre_data = get_plan_cadre(cours_id=1, db_path='programme.db')
    
    # Afficher le JSON
    if plan_cadre_data:
        print(json.dumps(plan_cadre_data, indent=4))
