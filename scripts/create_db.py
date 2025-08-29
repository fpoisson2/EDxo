# create_db.py
import sqlite3

def drop_tables(conn):
    cursor = conn.cursor()
    # Désactiver les clés étrangères pour éviter les erreurs lors des suppressions
    cursor.execute('PRAGMA foreign_keys = OFF;')

    # Liste des tables à supprimer dans l'ordre approprié (dépendances en premier)
    tables = [
        'PlanCadreCapaciteMoyensEvaluation',
        'PlanCadreCapaciteSavoirsFaire',
        'PlanCadreCapaciteSavoirsNecessaires',
        'PlanCadreCapacites',
        'PlanCadreSavoirEtre',
        'PlanCadreCompetencesDeveloppees',
        'PlanCadreObjetsCibles',
        'PlanCadreCoursRelies',
        'PlanCadreCoursPrealables',
        'PlanCadre',
        'ElementCompetenceParCours',
        'CompetenceParCours',
        'CoursCorequis',
        'CoursPrealable',
        'FilConducteur',
        'ElementCompetenceCriteria',
        'ElementCompetence',
        'Competence',
        'Cours',
        'Programme'
    ]

    for table in tables:
        cursor.execute(f'DROP TABLE IF EXISTS {table};')
        print(f"Table '{table}' supprimée.")

    # Réactiver les clés étrangères
    cursor.execute('PRAGMA foreign_keys = ON;')
    conn.commit()

def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys = ON;')

    # --------------------- Tables Principales ---------------------

    # Table Programme
    cursor.execute("""
        CREATE TABLE Programme (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE
        );
    """)

    # Table Cours
    cursor.execute("""
        CREATE TABLE Cours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            programme_id INTEGER NOT NULL,
            code TEXT NOT NULL UNIQUE,
            nom TEXT NOT NULL,
            nombre_unites REAL NOT NULL,
            session INTEGER NOT NULL,
            heures_theorie INTEGER NOT NULL,
            heures_laboratoire INTEGER NOT NULL,
            heures_travail_maison INTEGER NOT NULL,
            FOREIGN KEY (programme_id) REFERENCES Programme(id) ON DELETE CASCADE
        );
    """)

    # Table Competence
    cursor.execute("""
        CREATE TABLE Competence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            programme_id INTEGER NOT NULL,
            code TEXT NOT NULL UNIQUE,
            nom TEXT NOT NULL,
            criteria_de_performance TEXT,
            contexte_de_realisation TEXT,
            FOREIGN KEY (programme_id) REFERENCES Programme(id) ON DELETE CASCADE
        );
    """)

    # Table ElementCompetence
    cursor.execute("""
        CREATE TABLE ElementCompetence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competence_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            FOREIGN KEY (competence_id) REFERENCES Competence(id) ON DELETE CASCADE,
            UNIQUE (competence_id, nom)
        );
    """)

    # Table ElementCompetenceCriteria
    cursor.execute("""
        CREATE TABLE ElementCompetenceCriteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            element_competence_id INTEGER NOT NULL,
            criteria TEXT NOT NULL,
            FOREIGN KEY (element_competence_id) REFERENCES ElementCompetence(id) ON DELETE CASCADE
        );
    """)

    # Table FilConducteur
    cursor.execute("""
        CREATE TABLE FilConducteur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            programme_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (programme_id) REFERENCES Programme(id) ON DELETE CASCADE
        );
    """)

    # Table CoursPrealable
    cursor.execute("""
        CREATE TABLE CoursPrealable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cours_id INTEGER NOT NULL,
            cours_prealable_id INTEGER NOT NULL,
            note_necessaire INTEGER,
            FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE,
            FOREIGN KEY (cours_prealable_id) REFERENCES Cours(id) ON DELETE CASCADE
        );
    """)

    # Table CoursCorequis
    cursor.execute("""
        CREATE TABLE CoursCorequis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cours_id INTEGER NOT NULL,
            cours_corequis_id INTEGER NOT NULL,
            FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE,
            FOREIGN KEY (cours_corequis_id) REFERENCES Cours(id) ON DELETE CASCADE
        );
    """)

    # Table CompetenceParCours
    cursor.execute("""
        CREATE TABLE CompetenceParCours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cours_id INTEGER NOT NULL,
            competence_developpee_id INTEGER NOT NULL,
            competence_atteinte_id INTEGER NOT NULL,
            FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE,
            FOREIGN KEY (competence_developpee_id) REFERENCES Competence(id) ON DELETE CASCADE,
            FOREIGN KEY (competence_atteinte_id) REFERENCES Competence(id) ON DELETE CASCADE
        );
    """)

    # Table ElementCompetenceParCours
    cursor.execute("""
        CREATE TABLE ElementCompetenceParCours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cours_id INTEGER NOT NULL,
            element_competence_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Non traité',
            FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE,
            FOREIGN KEY (element_competence_id) REFERENCES ElementCompetence(id) ON DELETE CASCADE
        );
    """)

    # --------------------- Tables Plan Cadre ---------------------

    # Table PlanCadre
    cursor.execute("""
        CREATE TABLE PlanCadre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cours_id INTEGER NOT NULL UNIQUE,
            place_intro TEXT,
            objectif_terminal TEXT,
            structure_intro TEXT,
            structure_activites_theoriques TEXT,
            structure_activites_pratiques TEXT,
            structure_activites_prevues TEXT,  -- texte CKEditor
            eval_evaluation_sommative TEXT,
            eval_nature_evaluations_sommatives TEXT,
            eval_evaluation_de_la_langue TEXT,
            eval_evaluation_sommatives_apprentissages TEXT, -- CKEditor
            FOREIGN KEY (cours_id) REFERENCES Cours(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCompetencesDeveloppees
    cursor.execute("""
        CREATE TABLE PlanCadreCompetencesDeveloppees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreObjetsCibles
    cursor.execute("""
        CREATE TABLE PlanCadreObjetsCibles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCoursRelies
    cursor.execute("""
        CREATE TABLE PlanCadreCoursRelies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCoursPrealables
    cursor.execute("""
        CREATE TABLE PlanCadreCoursPrealables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCapacites
    cursor.execute("""
        CREATE TABLE PlanCadreCapacites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            capacite TEXT NOT NULL,
            description_capacite TEXT,
            ponderation_min INTEGER DEFAULT 0,
            ponderation_max INTEGER DEFAULT 0,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCapaciteSavoirsNecessaires
    cursor.execute("""
        CREATE TABLE PlanCadreCapaciteSavoirsNecessaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capacite_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            cible TEXT,
            seuil_reussite TEXT,
            FOREIGN KEY (capacite_id) REFERENCES PlanCadreCapacites(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCapaciteSavoirsFaire
    cursor.execute("""
        CREATE TABLE PlanCadreCapaciteSavoirsFaire (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capacite_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            cible TEXT,
            seuil_reussite TEXT,
            FOREIGN KEY (capacite_id) REFERENCES PlanCadreCapacites(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreCapaciteMoyensEvaluation
    cursor.execute("""
        CREATE TABLE PlanCadreCapaciteMoyensEvaluation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capacite_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (capacite_id) REFERENCES PlanCadreCapacites(id) ON DELETE CASCADE
        );
    """)

    # Table PlanCadreSavoirEtre
    cursor.execute("""
        CREATE TABLE PlanCadreSavoirEtre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_cadre_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY (plan_cadre_id) REFERENCES PlanCadre(id) ON DELETE CASCADE
        );
    """)

    conn.commit()
    print("Toutes les tables ont été créées avec succès.")

def main():
    DATABASE = 'programme.db'
    conn = sqlite3.connect(DATABASE)
    try:
        drop_tables(conn)
        create_tables(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
