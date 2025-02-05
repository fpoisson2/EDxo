import os
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from PyPDF2 import PdfReader
import logging

# ------------------------
# Configuration et dossiers
# ------------------------

# Configuration du logging
LOG_FILENAME = 'extraction.log'
logging.basicConfig(
    filename=LOG_FILENAME,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# URL de la page principale (non utilisé dans cette version simplifiée)
MAIN_PAGE = "https://www.quebec.ca/education/cegep/services/programmes/programmes-etudes-techniques"
BASE_PREFIX = MAIN_PAGE  # On limite aux liens débutant par cette URL

# Dossiers de sauvegarde
DOWNLOAD_FOLDER = "pdfs"
TXT_FOLDER = "txt_output"    # Dossier pour les fichiers TXT d'analyse

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(TXT_FOLDER, exist_ok=True)

# ------------------------
# Partie 1 : Téléchargement des PDF (inchangée)
# ------------------------

def get_page_content(url):
    """Récupère le contenu HTML d'une page donnée."""
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.text
        else:
            print(f"Erreur {response.status_code} pour {url}")
    except Exception as e:
        print(f"Erreur lors de la connexion à {url}: {e}")
    return None

def extract_subpage_links(html, current_url):
    """
    Extrait les liens vers les sous-pages appartenant à la branche définie (BASE_PREFIX)
    et différents de current_url.
    """
    soup = BeautifulSoup(html, "html.parser")
    subpages = set()
    for a in soup.find_all("a", href=True):
        link = urljoin(current_url, a['href'])
        # Exclure certains schémas
        if link.startswith("mailto:") or link.startswith("javascript:"):
            continue
        # On ne garde que les pages de la branche et différentes de la page actuelle
        if link.startswith(BASE_PREFIX) and link != current_url:
            subpages.add(link)
    return list(subpages)

def download_pdfs_from_html(html, current_url):
    """
    Parcourt le HTML et télécharge les PDF trouvés sur la page.
    Si le fichier est déjà présent dans le dossier DOWNLOAD_FOLDER,
    le téléchargement est ignoré.
    """
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        link = urljoin(current_url, a["href"])
        if link.lower().endswith(".pdf"):
            filename = os.path.basename(urlparse(link).path)
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            
            if os.path.exists(file_path):
                print(f"Le fichier {filename} existe déjà. Téléchargement ignoré.")
            else:
                print("Téléchargement de :", link)
                try:
                    response = requests.get(link)
                    if response.status_code == 200:
                        with open(file_path, "wb") as f:
                            f.write(response.content)
                        print("Fichier sauvegardé sous :", file_path)
                    else:
                        print("Erreur lors du téléchargement de", link, "-", response.status_code)
                        continue
                except Exception as e:
                    print(f"Erreur lors du téléchargement de {link}: {e}")
                    continue

def main_download():
    # Récupérer le contenu de la page principale
    main_html = get_page_content(MAIN_PAGE)
    if not main_html:
        print("Impossible de récupérer la page principale.")
        return

    # Extraction des sous-pages depuis la page principale
    subpages = extract_subpage_links(main_html, MAIN_PAGE)
    if not subpages:
        print("Aucune sous-page trouvée sur la page principale.")
        return

    print("Sous-pages trouvées :")
    for sp in subpages:
        print(" -", sp)

    # Pour chaque sous-page, télécharger les PDF qui s'y trouvent
    for subpage_url in subpages:
        print("\nAccès à la sous-page :", subpage_url)
        subpage_html = get_page_content(subpage_url)
        if subpage_html:
            download_pdfs_from_html(subpage_html, subpage_url)
        else:
            print("Impossible de récupérer la sous-page :", subpage_url)

# ------------------------
# Partie 2 : Conversion des PDF en TXT
# ------------------------

def extract_text_from_pdf(pdf_path):
    """
    Extrait le texte complet du PDF en concaténant le contenu de chaque page.
    """
    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"Erreur lors de l'ouverture de {pdf_path} : {e}")
        return ""
    
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"
    return full_text

def process_pdf_to_txt(pdf_path):
    """
    Extrait le texte complet du PDF et le sauvegarde dans un fichier TXT pour analyse.
    L'extraction est effectuée uniquement si le fichier TXT de sortie n'existe pas déjà.
    """
    base_filename = os.path.basename(pdf_path).replace(".pdf", "")
    output_filename = f"{base_filename}.txt"
    output_path = os.path.join(TXT_FOLDER, output_filename)
    
    if os.path.exists(output_path):
        print(f"Le fichier TXT {output_filename} existe déjà. Extraction ignorée pour {pdf_path}.")
        return

    print(f"\nTraitement TXT pour {pdf_path}")
    full_text = extract_text_from_pdf(pdf_path)
    if not full_text:
        print("Aucun texte extrait.")
        return

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print(f"Texte extrait sauvegardé dans {output_path}")
    except Exception as e:
        print(f"Erreur lors de l'écriture dans {output_path} : {e}")

def process_downloaded_pdfs_to_txt():
    """
    Parcourt tous les PDF présents dans le dossier DOWNLOAD_FOLDER
    et les convertit en fichiers TXT.
    """
    for filename in os.listdir(DOWNLOAD_FOLDER):
        if filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(DOWNLOAD_FOLDER, filename)
            process_pdf_to_txt(pdf_path)

# ------------------------
# Partie 3 : Extraction des compétences ministérielles depuis les fichiers TXT
# ------------------------

import re

def extract_competencies(text):
    # Normaliser les retours à la ligne (optionnel)
    #text = re.sub(r'\n+', '\n', text)
    
    # Définir le pattern :
    # - [0-9][0-9A-Z]{3} : le code (un chiffre suivi de 3 caractères majuscules ou chiffres)
    # - \s{1,2}          : une ou deux espaces
    # - [A-Za-z]         : une lettre majuscule ou minuscule
    # - .*?\.            : capture non-gourmande de tout caractère jusqu'au premier point rencontré
    # - \s*(?=\n|$)      : autoriser des espaces optionnels avant un saut de ligne ou la fin du texte
    pattern = re.compile(r"\d{4}[A-Z]? (.*?)\.\s*$", re.MULTILINE)  
    
    # Rechercher toutes les correspondances dans le texte
    competencies = pattern.findall(text)
    
    return competencies


def process_txt_files_for_competencies():
    """
    Parcourt tous les fichiers TXT du dossier TXT_FOLDER,
    extrait les compétences ministérielles et affiche les résultats.
    """
    for filename in os.listdir(TXT_FOLDER):
        if filename.lower().endswith(".txt"):
            txt_path = os.path.join(TXT_FOLDER, filename)
            print(f"\nTraitement du fichier TXT : {txt_path}")
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Erreur lors de la lecture de {txt_path} : {e}")
                continue

            competencies = extract_competencies(content)
            if competencies:
                print("Compétences trouvées :")
                for code in competencies:
                    print(f"  {code}")
            else:
                print("Aucune compétence extraite dans ce fichier.")

# ------------------------
# Programme principal
# ------------------------

if __name__ == "__main__":
    # Pour télécharger les PDF depuis le site, décommentez la ligne suivante :
    # main_download()
    
    # Conversion de tous les PDF téléchargés en fichiers TXT (si non déjà extraits)
    process_downloaded_pdfs_to_txt()
    
    # Extraction des compétences ministérielles depuis les fichiers TXT
    process_txt_files_for_competencies()
