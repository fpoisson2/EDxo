# constants.py

SECTIONS = [
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
    'Description des compétences développées', #plusieurs
    'Description des Compétences certifiées', #plusieurs
    'Description des cours corequis', #plusieurs
    'Objets cibles', #plusieurs
    'Description des cours reliés', #plusieurs
    'Description des cours préalables', #plusieurs
    'Savoir-être', #plusieurs
    'Capacité et pondération', #plusieurs
    'Savoirs nécessaires d\'une capacité', #plusieurs
    'Savoirs faire d\'une capacité', #plusieurs
    'Moyen d\'évaluation d\'une capacité' #plusieurs
]


# --- CONFIGURATION FICHIERS ET DOSSIERS ---
MARKDOWN_FILENAME = "output_avec_pages.md"
DOWNLOADED_PDF_PREFIX = "original_" # Préfixe pour le nom du PDF original téléchargé
SECTION_PDF_FILENAME = "section_detectee.pdf"
TXT_OUTPUT_FILENAME = "document_extrait.txt"
JSON_OUTPUT_FILENAME = "competences_extraites.json"

# URL de base
MAIN_PAGE = "https://www.quebec.ca/education/cegep/services/programmes/programmes-etudes-techniques"
# BASE_PREFIX n'est plus nécessaire si on utilise urljoin correctement

# Dossiers
DOWNLOAD_FOLDER = "pdfs"
TXT_FOLDER = "txt_output" # Peut-être renommer en 'output' ou similaire si d'autres sorties y vont
LOG_FILENAME = 'extraction.log'