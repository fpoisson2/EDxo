# insert_data.py
import json
import sqlite3


def array_to_html_list(items):
    """
    Convertit une liste imbriquée en une chaîne HTML de listes à puces.
    Les éléments peuvent être des chaînes ou des dictionnaires avec 'text' et 'children'.
    """
    html = '<ul>'
    for item in items:
        if isinstance(item, str):
            html += f'<li>{item}</li>'
        elif isinstance(item, dict) and 'text' in item:
            html += f'<li>{item["text"]}'
            if 'children' in item and isinstance(item['children'], list):
                html += array_to_html_list(item['children'])
            html += '</li>'
    html += '</ul>'
    return html

def insert_programme(conn, nom):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Programme (nom)
        VALUES (?)
    """, (nom,))
    return cursor.lastrowid

def insert_competence(conn, programme_id, code, nom, criteria_de_performance, contexte_de_realisation):
    cursor = conn.cursor()
    
    # Convertir les listes en HTML
    if isinstance(criteria_de_performance, list):
        criteria_html = array_to_html_list(criteria_de_performance)
    else:
        criteria_html = criteria_de_performance
    
    if isinstance(contexte_de_realisation, list):
        contexte_html = array_to_html_list(contexte_de_realisation)
    else:
        contexte_html = contexte_de_realisation
    
    cursor.execute("""
        INSERT INTO Competence (programme_id, code, nom, criteria_de_performance, contexte_de_realisation)
        VALUES (?, ?, ?, ?, ?)
    """, (programme_id, code, nom, criteria_html, contexte_html))
    return cursor.lastrowid

def insert_element_competence(conn, competence_id, nom):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ElementCompetence (competence_id, nom)
        VALUES (?, ?)
    """, (competence_id, nom))
    return cursor.lastrowid

def insert_element_criteria(conn, element_competence_id, criteria):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ElementCompetenceCriteria (element_competence_id, criteria)
        VALUES (?, ?)
    """, (element_competence_id, criteria))
    return cursor.lastrowid

def main():
    # Charger les données JSON
    with open('data_rt.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = sqlite3.connect('programme.db')
    try:
        conn.execute('BEGIN TRANSACTION;')

        # Insérer le programme
        programme_nom = data["programme"]
        programme_id = insert_programme(conn, programme_nom)
        print(f"Programme inséré avec l'ID : {programme_id}")

        # Insérer les compétences
        for comp in data["competences"]:
            competence_id = insert_competence(
                conn,
                programme_id,
                comp["code"],
                comp["nom"],
                comp["criteria_de_performance"],
                comp["contexte_de_realisation"]
            )
            print(f"Compétence '{comp['nom']}' insérée avec l'ID : {competence_id}")

            # Insérer les éléments de compétence
            for elem in comp["elements"]:
                element_id = insert_element_competence(conn, competence_id, elem["nom"])
                print(f"  Élément de compétence '{elem['nom']}' inséré avec l'ID : {element_id}")

                # Insérer les critères de performance de l'élément de compétence
                for crit in elem["criteria"]:
                    insert_element_criteria(conn, element_id, crit)
                    print(f"    Critère de performance ajouté : {crit}")

        conn.commit()
        print("Toutes les données ont été insérées avec succès.")
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"Erreur d'intégrité : {e}")
    except Exception as e:
        conn.rollback()
        print(f"Une erreur s'est produite : {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
