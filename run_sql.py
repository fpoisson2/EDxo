import sqlite3

# Chemin vers votre base de données et le fichier SQL
db_path = 'programme.db'
sql_file_path = 'competences_and_elements.sql'

# Charger et exécuter le script SQL
with sqlite3.connect(db_path) as conn:
    with open(sql_file_path, 'r') as f:
        sql_script = f.read()
    conn.executescript(sql_script)
    print("Script exécuté avec succès !")
