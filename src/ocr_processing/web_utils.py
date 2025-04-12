# -*- coding: utf-8 -*-
import requests
import os
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import config # Importer pour accéder aux constantes comme DOWNLOAD_FOLDER

def get_page_content(url):
    """Récupère le contenu HTML d'une page donnée."""
    logging.info(f"Tentative de récupération du contenu de : {url}")
    try:
        response = requests.get(url, timeout=30) # Ajout d'un timeout
        response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)
        logging.info(f"Contenu de {url} récupéré avec succès.")
        return response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la connexion à {url} : {e}")
        print(f"Erreur lors de la connexion à {url} : {e}")
        return None

def extract_secteur_links(html, current_url):
    """
    Extrait les secteurs depuis le menu secondaire sous forme de tuples (nom, url).
    """
    soup = BeautifulSoup(html, "html.parser")
    secteurs = []
    nav = soup.find("nav", class_="menu-sec")
    if not nav:
        logging.warning(f"Menu secondaire 'menu-sec' non trouvé sur {current_url}")
        return secteurs

    # On parcourt les éléments <li> de classe "menu-sec-subitem"
    for li in nav.find_all("li", class_="menu-sec-subitem"):
        a = li.find("a", href=True)
        if a:
            nom = a.get_text(" ", strip=True)
            url = urljoin(current_url, a['href']) # Utilise urljoin pour gérer les URL relatives/absolues
            secteurs.append((nom, url))
            logging.debug(f"Secteur trouvé (lien) : {nom} - {url}")
        else:
            # Pour l'élément courant (sans balise <a>), on récupère le texte du span
            span = li.find("span", class_="menu-sec-subitem-lien")
            if span:
                nom = span.get_text(" ", strip=True)
                # Utilisation de current_url pour l'URL dans ce cas (page actuelle)
                secteurs.append((nom, current_url))
                logging.debug(f"Secteur trouvé (actuel) : {nom} - {current_url}")

    logging.info(f"{len(secteurs)} secteurs trouvés sur {current_url}")
    return secteurs

def extract_pdf_links_from_subpage(html, current_url):
    """
    Extrait les liens PDF depuis une page de secteur.
    Retourne une liste de tuples (titre, lien_pdf).
    """
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    seen_urls = set() # Pour éviter les doublons si le même PDF est lié plusieurs fois

    for a in soup.find_all("a", href=True):
        href = a['href']
        if href.lower().endswith(".pdf"):
            lien_pdf = urljoin(current_url, href)
            if lien_pdf not in seen_urls:
                titre = a.get_text(" ", strip=True)
                if not titre: # Si le lien n'a pas de texte (ex: image), essayer de trouver un titre autrement
                    titre = os.path.basename(urlparse(lien_pdf).path) # Utiliser le nom de fichier
                pdf_links.append((titre, lien_pdf))
                seen_urls.add(lien_pdf)
                logging.debug(f"Lien PDF trouvé : {titre} - {lien_pdf}")

    logging.info(f"{len(pdf_links)} liens PDF trouvés sur {current_url}")
    return pdf_links

def telecharger_pdf(pdf_url, output_directory):
    """Télécharge le PDF et le sauvegarde dans le dossier spécifié."""
    try:
        # Générer un nom de fichier sûr à partir de l'URL
        parsed_url = urlparse(pdf_url)
        pdf_basename = os.path.basename(parsed_url.path)
        # Nettoyer un peu le nom de fichier si nécessaire (optionnel)
        safe_filename = "".join(c for c in pdf_basename if c.isalnum() or c in ('.', '_', '-')).rstrip()
        if not safe_filename.lower().endswith(".pdf"):
             safe_filename += ".pdf" # Assurer l'extension

        output_filename = os.path.join(output_directory, safe_filename)

        if os.path.exists(output_filename):
            logging.info(f"Le fichier PDF existe déjà : {output_filename}")
            print(f"Le fichier PDF existe déjà : {output_filename}")
            return output_filename # Retourner le chemin existant

        logging.info(f"Téléchargement du PDF depuis {pdf_url} vers {output_filename}...")
        print(f"Téléchargement du PDF depuis {pdf_url}...")
        response = requests.get(pdf_url, timeout=60) # Augmenter le timeout pour les gros PDF
        response.raise_for_status()

        # Ensure the output directory exists
        os.makedirs(output_directory, exist_ok=True)
        # Now open the file
        with open(output_filename, "wb") as f:
            f.write(response.content)

        with open(output_filename, "wb") as f:
            f.write(response.content)
        logging.info(f"PDF téléchargé avec succès : {output_filename}")
        print("Téléchargement terminé.")
        return output_filename # Retourner le chemin du fichier téléchargé

    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors du téléchargement du PDF depuis {pdf_url}: {e}")
        print(f"Erreur lors du téléchargement du PDF : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors du téléchargement du PDF {pdf_url}: {e}")
        print(f"Erreur inattendue lors du téléchargement : {e}")
        return None