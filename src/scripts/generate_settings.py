# initialize_global_settings.py

import sqlite3

from constants import SECTIONS

DATABASE = 'programme.db'

def initialize_global_generation_settings():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    for section in SECTIONS:
        cursor.execute('''
            INSERT OR IGNORE INTO GlobalGenerationSettings (section, use_ai, text_content)
            VALUES (?, ?, ?)
        ''', (section, False, ''))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialize_global_generation_settings()
    print("Paramètres globaux de génération initialisés.")
