import sqlite3

def update_unites(conn):
    cursor = conn.cursor()

    # Récupérer tous les cours
    cursor.execute('SELECT id, heures_theorie, heures_laboratoire, heures_travail_maison FROM Cours')
    cours = cursor.fetchall()

    for cours_row in cours:
        cours_id, heures_theorie, heures_laboratoire, heures_travail_maison = cours_row
        
        # Calculer le nombre d'unités
        nombre_unites = (heures_theorie + heures_laboratoire + heures_travail_maison) / 3
        
        # Mettre à jour le nombre d'unités dans la table Cours
        cursor.execute('''
            UPDATE Cours
            SET nombre_unites = ?
            WHERE id = ?
        ''', (nombre_unites, cours_id))
        print(f"Cours {cours_id} mis à jour avec {nombre_unites} unités.")

    # Sauvegarder les changements dans la base de données
    conn.commit()

def main():
    DATABASE = 'programme.db'  # Assurez-vous que c'est le bon chemin vers votre base de données
    conn = sqlite3.connect(DATABASE)

    try:
        update_unites(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
