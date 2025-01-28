# update_db.py
import sqlite3
import sys

def add_element_competence_id_column():
    conn = sqlite3.connect('programme.db')
    cursor = conn.cursor()
    
    # Vérifier si la colonne 'element_competence_id' existe déjà
    cursor.execute("PRAGMA table_info(ElementCompetenceParCours);")
    columns = [info[1] for info in cursor.fetchall()]
    if 'element_competence_id' not in columns:
        try:
            # Ajouter la colonne 'element_competence_id'
            cursor.execute("""
                ALTER TABLE ElementCompetenceParCours 
                ADD COLUMN element_competence_id INTEGER NOT NULL DEFAULT 0;
            """)
            conn.commit()
            print("Colonne 'element_competence_id' ajoutée à la table 'ElementCompetenceParCours'.")
        except sqlite3.OperationalError as e:
            print(f"Erreur lors de l'ajout de la colonne 'element_competence_id': {e}")
    else:
        print("La colonne 'element_competence_id' existe déjà dans 'ElementCompetenceParCours'.")

    conn.close()

def recreate_table_with_foreign_keys():
    conn = sqlite3.connect('programme.db')
    cursor = conn.cursor()

    try:
        # Créer une nouvelle table avec les contraintes de clé étrangère
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ElementCompetenceParCours_new (
                cours_id INTEGER NOT NULL,
                element_competence_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Non traité',
                PRIMARY KEY (cours_id, element_competence_id),
                FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE,
                FOREIGN KEY (element_competence_id) REFERENCES ElementCompetence(id) ON DELETE CASCADE
            );
        """)

        # Copier les données de l'ancienne table vers la nouvelle table
        cursor.execute("""
            INSERT INTO ElementCompetenceParCours_new (cours_id, element_competence_id, status)
            SELECT cours_id, element_competence_id, status FROM ElementCompetenceParCours;
        """)

        # Supprimer l'ancienne table
        cursor.execute("DROP TABLE ElementCompetenceParCours;")

        # Renommer la nouvelle table
        cursor.execute("ALTER TABLE ElementCompetenceParCours_new RENAME TO ElementCompetenceParCours;")

        conn.commit()
        print("Table 'ElementCompetenceParCours' recréée avec les contraintes de clé étrangère.")
    except sqlite3.OperationalError as e:
        print(f"Erreur lors de la recréation de la table: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    print("Vérification de la colonne 'element_competence_id'...")
    add_element_competence_id_column()
    print("\nRecréation de la table avec contraintes de clé étrangère...")
    recreate_table_with_foreign_keys()
