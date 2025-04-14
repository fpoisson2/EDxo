# EDxo/src/ocr_processing/web_utils.py

import requests
import os
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
# Assurez-vous que l'import de constants fonctionne ou passez MAIN_PAGE autrement
try:
    from config import constants
except ImportError:
    logging.error("Impossible d'importer constants depuis config dans web_utils.py")
    class constants: # Placeholder
        MAIN_PAGE = "URL_PAR_DEFAUT_MANQUANTE"

# Configurez le logger si ce n'est pas déjà fait au niveau de l'application
# logging.basicConfig(level=logging.INFO) # Déjà fait dans app/__init__.py normalement

def get_page_content(url):
    """Récupère le contenu HTML d'une page donnée, en suivant les redirections."""
    logging.info(f"Tentative de récupération du contenu de : {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Timeout augmenté et allow_redirects=True
        response = requests.get(url, timeout=60, headers=headers, allow_redirects=True)
        response.raise_for_status() # Vérifie les erreurs HTTP après redirection

        if response.url != url:
            logging.info(f"Redirigé vers : {response.url}")

        logging.info(f"Contenu de {response.url} récupéré avec succès (status {response.status_code}).")
        return response.text
    except requests.exceptions.Timeout:
        logging.error(f"Timeout dépassé lors de la connexion à {url}")
        print(f"Timeout dépassé lors de la connexion à {url}") # Utile pour le debug rapide
        return None
    except requests.exceptions.SSLError as ssl_e:
         logging.error(f"Erreur SSL/TLS lors de la connexion à {url} : {ssl_e}", exc_info=True)
         print(f"Erreur SSL/TLS lors de la connexion à {url} : {ssl_e}")
         return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur RequestException lors de la connexion à {url} : {e}", exc_info=True)
        print(f"Erreur RequestException lors de la connexion à {url} : {e}")
        return None
    except Exception as e:
         logging.error(f"Erreur inattendue dans get_page_content pour {url}: {e}", exc_info=True)
         print(f"Erreur inattendue dans get_page_content pour {url}: {e}")
         return None

def extract_secteur_links(html, current_url):
    """
    Extrait les secteurs depuis le menu secondaire sous forme de tuples (nom, url).
    (Logique de parsing potentiellement à ajuster si la structure du site change)
    """
    soup = BeautifulSoup(html, "html.parser")
    secteurs = []
    # Essayer de trouver la navigation principale (peut nécessiter adaptation)
    nav = soup.find("nav", class_="menu-sec") or soup.select_one('nav[aria-label*="secondaire"]')

    if not nav:
        logging.warning(f"Menu secondaire non trouvé sur {current_url} pour extraire les secteurs.")
        return secteurs

    # Chercher les liens directs ou les éléments de liste
    links = nav.find_all("a", href=True)
    if not links:
        list_items = nav.find_all("li")
        for li in list_items:
             a_tag = li.find('a', href=True)
             span_tag = li.find(['span', 'div'], class_=lambda x: x and 'lien' in x) # Plus flexible pour le span/div courant
             if a_tag:
                 nom = a_tag.get_text(" ", strip=True)
                 url = urljoin(current_url, a_tag['href'])
                 # S'assurer que l'URL est absolue et sur le domaine attendu
                 if url.startswith('http') and urlparse(url).netloc == urlparse(current_url).netloc:
                     secteurs.append((nom, url))
                     logging.debug(f"Secteur trouvé (lien li>a) : {nom} - {url}")
             elif span_tag and not a_tag: # Élément actif
                  nom = span_tag.get_text(" ", strip=True)
                  # Vérifier s'il n'est pas déjà ajouté (au cas où le lien est aussi présent)
                  if not any(s[0] == nom and s[1] == current_url for s in secteurs):
                      secteurs.append((nom, current_url))
                      logging.debug(f"Secteur trouvé (actuel li>span/div) : {nom} - {current_url}")
    else:
        for a in links:
             nom = a.get_text(" ", strip=True)
             url = urljoin(current_url, a['href'])
             if url.startswith('http') and urlparse(url).netloc == urlparse(current_url).netloc:
                 # S'assurer de ne pas ajouter la page courante si elle a aussi un lien vers elle-même
                 if url != current_url or not any(s[0] == nom for s in secteurs):
                     secteurs.append((nom, url))
                     logging.debug(f"Secteur trouvé (lien direct nav>a) : {nom} - {url}")

    # Dé-duplication finale au cas où
    unique_secteurs = []
    seen_urls = set()
    for nom, url in secteurs:
        if url not in seen_urls:
            unique_secteurs.append((nom, url))
            seen_urls.add(url)

    logging.info(f"{len(unique_secteurs)} secteurs uniques trouvés sur {current_url}")
    return unique_secteurs


def extract_pdf_links_from_subpage(html, current_url):
    """
    Extrait les liens PDF depuis une page de secteur.
    Retourne une liste de tuples (titre, lien_pdf).
    """
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    seen_urls = set()
    main_content = soup.find("main") or soup.find(id="main") or soup.body
    if not main_content: main_content = soup

    for a in main_content.find_all("a", href=True):
        href = a.get('href', '')
        if href.lower().endswith(".pdf"):
            lien_pdf = urljoin(current_url, href)
            if lien_pdf not in seen_urls and lien_pdf.startswith('http'):
                titre = a.get_text(" ", strip=True)
                if not titre:
                    parent_header = a.find_parent(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                    if parent_header: titre = parent_header.get_text(" ", strip=True)
                if not titre: titre = os.path.basename(urlparse(lien_pdf).path)

                titre = titre.replace("(PDF)", "").replace(".pdf", "").strip()
                if titre: # S'assurer qu'on a un titre
                    pdf_links.append((titre, lien_pdf))
                    seen_urls.add(lien_pdf)
                    logging.debug(f"Lien PDF trouvé : {titre} - {lien_pdf}")

    logging.info(f"{len(pdf_links)} liens PDF trouvés sur {current_url}")
    return pdf_links


def telecharger_pdf(pdf_url, output_directory):
    """Télécharge le PDF et le sauvegarde dans le dossier spécifié."""
    try:
        parsed_url = urlparse(pdf_url)
        pdf_basename = os.path.basename(parsed_url.path)
        # Nettoyage plus robuste du nom de fichier
        safe_filename = "".join(c for c in pdf_basename if c.isalnum() or c in ('-', '_')).strip()
        safe_filename = safe_filename or f"pdf_{hash(pdf_url)}" # Nom par défaut si vide
        safe_filename += ".pdf" # Assurer l'extension

        output_filename = os.path.join(output_directory, safe_filename)

        if os.path.exists(output_filename):
            logging.info(f"Le fichier PDF existe déjà : {output_filename}")
            return output_filename

        logging.info(f"Téléchargement du PDF depuis {pdf_url} vers {output_filename}...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(pdf_url, timeout=120, headers=headers, allow_redirects=True)
        response.raise_for_status()

        os.makedirs(output_directory, exist_ok=True)
        with open(output_filename, "wb") as f:
            f.write(response.content)
        logging.info(f"PDF téléchargé avec succès : {output_filename}")
        return output_filename

    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors du téléchargement du PDF {pdf_url}: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors du téléchargement du PDF {pdf_url}: {e}", exc_info=True)
        return None