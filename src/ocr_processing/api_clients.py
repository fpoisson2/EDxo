# -*- coding: utf-8 -*-
# api_clients.py
from flask import current_app
import logging
import json

from openai import OpenAI
import os # Ajout de os pour manipuler les chemins

# === DÉFINIR L'EXCEPTION PERSONNALISÉE ===
class SkillExtractionError(Exception):
    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception
        # On ajoute explicitement un attribut 'exc_type'
        self.exc_type = type(original_exception).__name__ if original_exception else self.__class__.__name__

    def __reduce__(self):
        # Ceci permet à Celery de sérialiser correctement l'exception
        return (self.__class__, (self.message, self.original_exception))


# =========================================


# --- Fonction perform_ocr_and_save (Garder `print` pour debug console si désiré) ---
def perform_ocr_and_save(pdf_url_or_path, output_markdown_filename):
    """
    Convertit un PDF en markdown simple page-par-page sans dépendre d'un service OCR externe.
    - Si une URL est fournie, télécharge le PDF d'abord.
    - Écrit un fichier avec des sections '## --- Page N ---' suivies du texte extrait.

    Remarque: Pour les PDF scannés (images), PyPDF2 peut extraire peu de texte.
    """
    try:
        from PyPDF2 import PdfReader
        from . import web_utils
    except Exception as imp_err:
        logging.error(f"Dépendances manquantes pour la conversion PDF->markdown: {imp_err}")
        return False

    try:
        # Déterminer le chemin local du PDF
        local_pdf_path = pdf_url_or_path
        if isinstance(pdf_url_or_path, str) and pdf_url_or_path.startswith('http'):
            out_dir = os.path.dirname(output_markdown_filename) or '.'
            os.makedirs(out_dir, exist_ok=True)
            downloaded = web_utils.telecharger_pdf(pdf_url_or_path, out_dir)
            if not downloaded:
                logging.error(f"Échec du téléchargement du PDF depuis {pdf_url_or_path}")
                return False
            local_pdf_path = downloaded

        if not os.path.exists(local_pdf_path):
            logging.error(f"Fichier PDF introuvable: {local_pdf_path}")
            return False

        logging.info(f"Conversion PDF->markdown local: {local_pdf_path} -> {output_markdown_filename}")
        reader = PdfReader(local_pdf_path)
        with open(output_markdown_filename, 'w', encoding='utf-8') as out:
            for i, page in enumerate(reader.pages, start=1):
                out.write(f"## --- Page {i} ---\n\n")
                try:
                    text = page.extract_text() or ''
                except Exception as e:
                    logging.warning(f"Erreur d'extraction texte page {i}: {e}")
                    text = ''
                if text.strip():
                    out.write(text.strip() + "\n\n")
                else:
                    out.write("*[Texte non extrait pour cette page]*\n\n")
        logging.info(f"Markdown OCR-like généré: {output_markdown_filename}")
        return True
    except Exception as e:
        logging.error(f"Erreur lors de la conversion PDF->markdown: {e}", exc_info=True)
        return False

def _get_ocr_settings_safely():
    try:
        from src.app.models import OcrPromptSettings
        return OcrPromptSettings.get_current()
    except Exception:
        return None


def find_competences_pages(markdown_content, openai_key=None, pdf_path: str | None = None):
    """
    Utilise l'API OpenAI pour identifier la section 'Formation spécifique'
    et segmenter cette section en plusieurs blocs correspondant à chaque compétence.
    L'IA doit retourner un JSON respectant le schéma suivant :
    
    {
        "competences": [
            {
                "code": "04A0", 
                "page_debut": 3, 
                "page_fin": 8
            },
            {
                "code": "04A1", 
                "page_debut": 9, 
                "page_fin": 14
            },
            ... (autres compétences)
        ]
    }
    
    Cela permettra de traiter une compétence à la fois.
    """
    # Préparer le prompt pour que l'IA segmente la section en retournant
    # un tableau des bornes de page pour chaque compétence.
    settings = _get_ocr_settings_safely()
    system_prompt = (
        (settings.segmentation_prompt if (settings and settings.segmentation_prompt) else
         "Rôle : Assistant IA expert en analyse de documents OCRés de programmes d'études collégiales québécois.\n\n"
         "Objectif : Identifier la section 'Formation spécifique' et segmenter cette section en plusieurs compétences. "
         "Pour chaque compétence, retourne son code ainsi que la page de début et la page de fin correspondantes. "
         "Le résultat doit être un objet JSON strict respectant le schéma suivant :\n"
         "{\n"
         '  "competences": [\n'
         "    { \"code\": \"04A0\", \"page_debut\": <numéro>, \"page_fin\": <numéro> },\n"
         "    ...\n"
         "  ]\n"
         "}\n\n"
         "Assure-toi que 'page_debut' est la page où débute la compétence et 'page_fin' est la dernière page où elle se termine. "
         "Utilise uniquement les pages comportant des informations de compétences (l'énoncé, le contexte, les éléments et les critères).\n\n"
         "Voici le document OCRé en Markdown (avec indicateurs de page comme '## --- Page <numéro> ---') :\n")
    )
    
    prompt_content = system_prompt + "\n" + markdown_content
    messages = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "input_text", "text": prompt_content}]}
    ]
    
    # Schéma JSON requis
    json_schema = {
        "type": "object",
        "required": ["competences"],
        "properties": {
            "competences": {
                "type": "array",
                "description": "Liste des compétences avec leur code et bornes de pages.",
                "items": {
                    "type": "object",
                    "required": ["code", "page_debut", "page_fin"],
                    "properties": {
                        "code": {"type": "string", "description": "Code de la compétence (ex: 04A0)."},
                        "page_debut": {"type": "integer", "description": "Page de début de la compétence."},
                        "page_fin": {"type": "integer", "description": "Page de fin de la compétence."}
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False
    }
    
    try:
        # Fallback à la config si non fourni
        api_key = openai_key or current_app.config.get('OPENAI_API_KEY')
        openai_client = OpenAI(api_key=api_key)
    except Exception as e:
        raise Exception(f"Erreur lors de l'initialisation d'OpenAI : {e}")

    # Si un chemin PDF est fourni et existe, préférer une analyse du document natif
    file_id = None
    try:
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                up = openai_client.files.create(file=f, purpose='user_data')
                file_id = getattr(up, 'id', None)
                logging.info(f"PDF uploadé pour segmentation (file_id={file_id})")
    except Exception as up_err:
        logging.warning(f"Échec upload PDF pour segmentation, fallback markdown: {up_err}")
        file_id = None

    try:
        model_section = (settings.model_section if (settings and settings.model_section) else current_app.config.get('OPENAI_MODEL_SECTION'))
        if file_id:
            # Utiliser le fichier et une instruction compacte
            response = openai_client.responses.create(
                model=model_section,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": file_id},
                        {"type": "input_text", "text": system_prompt}
                    ]
                }],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "CompetencePages",
                        "strict": True,
                        "schema": json_schema
                    }
                },
                reasoning={}, tools=[], tool_choice="none",
                max_output_tokens=1200, store=True
            )
        else:
            # Fallback: utiliser le markdown OCR
            response = openai_client.responses.create(
                model=model_section,
                input=messages,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "CompetencePages",
                        "strict": True,
                        "schema": json_schema
                    }
                },
                reasoning={}, tools=[], tool_choice="none",
                max_output_tokens=1000, store=True
            )

        # Récupération robuste du texte de sortie (différents SDK peuvent structurer différemment)
        json_response_str = None
        try:
            json_response_str = response.output[0].content[0].text  # chemin habituel
        except Exception:
            pass
        if not json_response_str:
            json_response_str = getattr(response, 'output_text', None)
        if not json_response_str:
            # Essayer d'agréger les items de sortie
            try:
                parts = []
                for item in getattr(response, 'output', []) or []:
                    content_list = getattr(item, 'content', None)
                    if isinstance(content_list, list):
                        for c in content_list:
                            t = getattr(c, 'text', None)
                            if t:
                                parts.append(t)
                if parts:
                    json_response_str = "".join(parts)
            except Exception:
                pass
        if not json_response_str:
            raise ValueError("Réponse OpenAI sans texte de sortie exploitable pour la segmentation.")

        pages_info = json.loads(json_response_str)
        usage_info = getattr(response, 'usage', None)
        return {"result": pages_info, "usage": usage_info}
    except Exception as e:
        raise Exception(f"Erreur lors de l'appel à OpenAI pour segmentation des compétences : {e}")
    finally:
        # Nettoyer le fichier uploadé côté OpenAI
        try:
            if file_id:
                openai_client.files.delete(file_id)
        except Exception as del_err:
            logging.warning(f"Échec suppression fichier OpenAI (file_id={file_id}): {del_err}")

def extraire_text_competence(markdown_content, page_debut, page_fin):
    """
    Extrait du contenu Markdown uniquement le texte situé entre page_debut et page_fin.
    
    On se base sur les marqueurs "## --- Page <numéro> ---". 
    """
    import re
    # Découper le Markdown en segments sur la base des pages
    segments = re.split(r'## --- Page (\d+) ---', markdown_content)
    texte_competence = ""
    # L'array 'segments' contient [texte_avant, num_page, texte, num_page, texte, ...]
    # On parcourt chaque bloc associé à un numéro de page et on reconstruit si le numéro est dans l'intervalle
    for i in range(1, len(segments), 2):
        try:
            num_page = int(segments[i].strip())
        except ValueError:
            continue
        if page_debut <= num_page <= page_fin:
            texte_competence += segments[i+1].strip() + "\n"
    return texte_competence.strip()

def extraire_toutes_les_competences(markdown_content, openai_key, output_json_filename, callback=None):
    """
    Combine les étapes :
     - Utilise find_competences_pages pour obtenir les bornes de pages pour chaque compétence.
     - Pour chacune, extrait le texte correspondant.
     - Pour chaque bloc, appelle extraire_competences_depuis_txt pour obtenir le JSON structuré.
     - Concatène les résultats dans une seule structure JSON sous la clé 'competences'.
    """
    # Obtenir la liste des compétences avec leurs bornes de pages
    pages_info = find_competences_pages(markdown_content, openai_key)
    if not pages_info or "competences" not in pages_info:
        raise Exception("Impossible d'identifier les bornes des compétences dans la section 'Formation spécifique'.")
    
    toutes_les_competences = []
    for comp in pages_info["competences"]:
        code_comp = comp.get("code")
        page_debut = comp.get("page_debut")
        page_fin = comp.get("page_fin")
        # Extraire le texte associé à ces pages
        texte_comp = extraire_text_competence(markdown_content, page_debut, page_fin)
        if not texte_comp:
            continue
        # Appeler extraire_competences_depuis_txt pour traiter ce bloc
        extraction_output = extraire_competences_depuis_txt(texte_comp, output_json_filename, openai_key, callback)
        try:
            competence_data = json.loads(extraction_output.get("result", "{}"))
            # On attend que competence_data soit du type {"competences": [...]}
            if "competences" in competence_data:
                # On peut éventuellement filtrer ou annoter avec le code identifié
                for comp_item in competence_data["competences"]:
                    if not comp_item.get("Code"):
                        comp_item["Code"] = code_comp
                    toutes_les_competences.append(comp_item)
        except Exception as e:
            if callback:
                callback({"type": "error", "message": f"Erreur lors du traitement du bloc (code {code_comp}) : {e}"})
    
    # Constitution du JSON final
    final_json = {"competences": toutes_les_competences}
    try:
        with open(output_json_filename, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=4)
    except Exception as e:
        if callback:
            callback({"type": "error", "message": f"Erreur lors de la sauvegarde du JSON final : {e}"})
    
    return final_json


# --- Fonction find_section_with_openai (Garder `print` pour debug console si désiré) ---
def find_section_with_openai(markdown_content, openai_key=None):
    """
    Utilise l'API OpenAI pour identifier la section "Formation spécifique".
    Retourne None en cas d'échec.
    """
    # --- Initialize client inside the function ---
    api_key = openai_key
    if not api_key:
        logging.error("Clé API OpenAI non trouvée dans la configuration. Impossible de trouver la section.")
        print("Erreur: Clé API OpenAI non configurée.")
        return None
    try:
        openai_client = OpenAI(api_key=api_key)
        logging.info("Client OpenAI initialisé pour find_section_with_openai.")
    except Exception as e:
        logging.error(f"Erreur initialisation client OpenAI dans find_section_with_openai: {e}")
        return None
    # --- End initialization ---


    # Définition du prompt système
    settings = _get_ocr_settings_safely()
    system_prompt = (
        "Rôle: Assistant IA expert en analyse de documents PDF de programmes d'études collégiales québécois.\n\n"
        "Objectif: Identifier précisément la section 'Formation spécifique' dans le document OCRé, et retourner les numéros de page de début et de fin de cette section.\n\n"
        "La section recherchée comprend les blocs suivants dans l'ordre: Énoncé de la compétence, Contexte de réalisation, Éléments, et Critères de performance."
    )
    # Structure des messages
    messages = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "input_text", "text": (
            "Voici le document OCRé en Markdown avec les indicateurs de page '## --- Page <numéro> ---'. Identifie la section contenant la 'Formation spécifique' "
            "(commençant typiquement par un code de compétence comme '0XXX' ou '0YYY', suivi de 'Énoncé de la compétence', 'Contexte de réalisation', 'Éléments', 'Critères de performance') "
            "et retourne **uniquement** le résultat au format JSON strict suivant : {'page_debut': <numéro>, 'page_fin': <numéro>}. "
            "Assure-toi que 'page_debut' est la page où commence le premier code de compétence de cette section, et 'page_fin' est la dernière page contenant des éléments ou critères de la dernière compétence de cette section spécifique.\n\n"
            + markdown_content
        )}]}
    ]
    # Schéma JSON
    json_schema = {
        "type": "object",
        "required": ["page_debut", "page_fin"],
        "properties": {
            "page_debut": {"type": "integer", "description": "Numéro de la page où commence la PREMIÈRE compétence de la section 'Formation spécifique'."},
            "page_fin": {"type": "integer", "description": "Numéro de la page où se termine la DERNIÈRE compétence de la section 'Formation spécifique'."}
        },
        "additionalProperties": False # Important pour la validation stricte
    }

    logging.info("Appel API OpenAI pour identifier la section...")
    print("Appel API OpenAI pour identifier la section...") # Pour console serveur
    try:
        model_section = (settings.model_section if (settings and settings.model_section) else current_app.config.get('OPENAI_MODEL_SECTION'))
        response = openai_client.responses.create(
            model=model_section,
            input=messages,
            text={"format": {"type": "json_schema", "name": "PageSection", "schema": json_schema, "strict": True}},
            reasoning={}, tools=[], tool_choice="none", temperature=0, max_output_tokens=1000, top_p=1, store=True,
            # request_timeout=60 # Optionnel
        )
        json_response_str = response.output[0].content[0].text
        logging.debug(f"Réponse brute d'OpenAI (section): {json_response_str}")
        page_info = json.loads(json_response_str)

        if not isinstance(page_info.get('page_debut'), int) or not isinstance(page_info.get('page_fin'), int) or page_info['page_debut'] <= 0 or page_info['page_fin'] < page_info['page_debut']:
            logging.error(f"Numéros de page invalides retournés par l'API: {page_info}")
            print(f"Erreur: Numéros de page invalides de l'API: {page_info}")
            return None

        logging.info(f"Section identifiée : Pages {page_info['page_debut']} à {page_info['page_fin']}")
        print(f"Section identifiée : Pages {page_info['page_debut']} à {page_info['page_fin']}") # Pour console serveur
        return {"result": page_info, "usage": getattr(response, "usage", None)}

    except json.JSONDecodeError as json_err:
        logging.error(f"Erreur de parsing JSON de la réponse OpenAI (section): {json_err}. Réponse brute: {json_response_str}", exc_info=False)
        print(f"Erreur parsing JSON (section): {json_err}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API OpenAI (section): {e}", exc_info=True)
        print(f"Erreur lors de l'appel API OpenAI (section): {e}") # Pour console serveur
        return None

def extraire_competences_depuis_txt(text_content, output_json_filename, openai_key=None, callback=None):
    """
    Extrait les compétences via API OpenAI (mode synchrone).
    Lève SkillExtractionError en cas d'échec.
    """
    # --- Initialisation du client ---
    api_key = openai_key or current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        msg = "Clé API OpenAI non trouvée dans la configuration. Impossible d'extraire les compétences."
        logging.error(msg)
        if callback:
            callback({"type": "error", "message": msg, "step": "skill_extract_init"})
        raise SkillExtractionError(msg)
    try:
        openai_client = OpenAI(api_key=api_key)
        logging.info("Client OpenAI initialisé pour extraire_competences_depuis_txt.")
    except Exception as e:
        msg = f"Erreur initialisation client OpenAI dans extraire_competences: {e}"
        logging.error(msg, exc_info=True)
        if callback:
            callback({"type": "error", "message": msg, "step": "skill_extract_init"})
        raise SkillExtractionError(msg) from e

    # --- Définition du prompt et du schéma ---
    settings = _get_ocr_settings_safely()
    system_prompt_inline = (
        """Tu es un assistant expert spécialisé dans l'extraction d'informations structurées à partir de documents textuels bruts, en particulier des descriptions de compétences de formation québécoises (souvent issues de PDF de programmes d'études).

Ton objectif principal est d'analyser le texte fourni par l'utilisateur, qui représente le contenu extrait d'un PDF (potentiellement bruité par l'OCR ou la conversion texte), d'identifier chaque bloc décrivant une compétence unique (généralement introduit par un code alphanumérique comme "Code : XXXX" ou "0XXX"), et d'en extraire méticuleusement les informations suivantes pour CHAQUE compétence trouvée:
1. Le `Code` de la compétence (ex: "02MU", "O1XY").
2. Le `Nom de la compétence` (le titre ou l'énoncé principal, ex: "Adopter un comportement professionnel.").
3. Le `Contexte de réalisation` : extrais toutes les lignes descriptives textuelles trouvées sous ce titre exact. Structure spécifiquement les sous-sections introduites par "À partir :" et "À l’aide :" comme des listes de chaînes de caractères dans des objets JSON imbriqués (`APartir`, `ALaide`) à l'intérieur de l'objet `Contexte de réalisation`. Les autres lignes descriptives générales vont dans `details_generaux`. Si une sous-section ("À partir de:", "À l'aide de:") est absente, sa valeur doit être `null` ou une liste vide. Si toute la section "Contexte de réalisation" est absente, sa valeur doit être `null`.
4. Les `Critères de performance pour l’ensemble de la compétence` : extrais les lignes descriptives textuelles trouvées sous ce titre exact sous forme de liste de chaînes de caractères. Si la section est absente ou marquée comme non applicable (ex: "S. O."), la valeur du champ doit être `null` ou une liste vide.
5. Les `Éléments` : Identifie chaque élément spécifique de la compétence (souvent numéroté `1.`, `2.`, etc., ou précédé d'une puce). Pour chaque élément, crée un objet contenant deux champs: `element` (la description textuelle de l'élément de compétence spécifique) et `criteres` (une liste de chaînes de caractères contenant les critères de performance associés *spécifiquement* à cet élément, trouvés immédiatement après la description de l'élément). Si aucun critère n'est listé pour un élément, `criteres` doit être `null` ou une liste vide. Si la section "Éléments" entière est absente, sa valeur doit être `null`.

Le contenu textuel extrait pour chaque champ doit être nettoyé : retire les puces/marqueurs de liste redondants (comme e, °, +, o, * au début des lignes si la structure est déjà une liste), les pieds de page fréquents ("Ministère...", "Code de programme XXX"), les numéros de page isolés sur une ligne, et les marqueurs de saut de page ("=== PAGE BREAK ==="). Assure-toi de conserver le sens et l'intégralité du texte pertinent.

Tu **dois impérativement** utiliser l'outil/fonction `extraire_competences_en_json` qui t'est fourni pour formater l'intégralité des données extraites pour *toutes* les compétences identifiées dans le texte source. Le résultat final DOIT être un unique objet JSON contenant une clé `competences` dont la valeur est une liste (array) d'objets, chaque objet représentant une compétence structurée selon le schéma. Respecte **strictement** et **exclusivement** le schéma JSON fourni dans les `parameters` de cet outil, y compris les types (`string`, `array`, `object`, `null`), les structures imbriquées et les champs requis (`required`). Ne fournis aucune explication, introduction, conclusion ou texte en dehors de l'appel à cette fonction structurée respectant le schéma demandé."""
    )
    if settings and settings.extraction_prompt:
        system_prompt_inline = settings.extraction_prompt
    json_schema = {
        "type": "object",
        "required": ["competences"],
        "properties": {
            "competences": {
                "type": "array",
                "description": "Liste des objets représentant chaque compétence extraite du texte source.",
                "items": {
                    "type": "object",
                    "required": [
                        "Code",
                        "Nom de la compétence",
                        "Contexte de réalisation",
                        "Critères de performance pour l’ensemble de la compétence",
                        "Éléments"
                    ],
                    "properties": {
                        "Code": {"type": "string", "description": "Code alphanumérique unique de la compétence (ex: 02MU)."},
                        "Nom de la compétence": {"type": "string", "description": "Le titre ou l'énoncé principal de la compétence."},
                        "Contexte de réalisation": {
                            "type": ["array", "null"],
                            "description": "Représente la structure hiérarchique du 'Contexte de réalisation'.",
                            "items": {"$ref": "#/definitions/context_item"}
                        },
                        "Critères de performance pour l’ensemble de la compétence": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "Liste des critères généraux."
                        },
                        "Éléments": {
                            "type": ["array", "null"],
                            "description": "Liste des éléments spécifiques décomposant la compétence.",
                            "items": {
                                "type": "object",
                                "required": ["element", "criteres"],
                                "properties": {
                                    "element": {"type": "string", "description": "Description de l'élément de compétence."},
                                    "criteres": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Liste des critères pour cet élément."}
                                },
                                "additionalProperties": False
                            }
                        }
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False,
        "definitions": {
            "context_item": {
                "type": "object",
                "required": ["texte", "sous_points"],
                "properties": {
                    "texte": {"type": "string", "description": "Contenu textuel du point principal ou sous-point."},
                    "sous_points": {"type": ["array", "null"], "description": "Liste des sous-points hiérarchiques.", "items": {"$ref": "#/definitions/context_item"}}
                },
                "additionalProperties": False
            }
        }
    }
    # --- Fin du prompt et du schéma ---

    logging.info("Appel API OpenAI pour extraction compétences en mode synchrone...")
    if callback:
        callback({"type": "info", "message": "Début de l'extraction des compétences...", "step": "skill_extract"})

    try:
        # Appel API sans mode stream
        response = openai_client.responses.create(
            model=current_app.config.get('OPENAI_MODEL_EXTRACTION'),
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt_inline}]},
                {"role": "user", "content": [{"type": "input_text", "text": text_content}]}
            ],
            text={"format": {"type": "json_schema", "name": "extraire_competences_en_json", "strict": True, "schema": json_schema}},
            reasoning={}, tools=[], tool_choice="none", store=True,
            stream=False  # Mode synchrone
        )


        logging.info("Test extraction usage: %s", getattr(response, "usage", None))

        # Récupération robuste du JSON
        try:
            logging.info(f"Réponse OpenAI reçue (type={type(response).__name__}). Tentative d'extraction du JSON...")
        except Exception:
            pass
        full_json_string = None
        try:
            full_json_string = response.output[0].content[0].text
        except Exception:
            pass
        if not full_json_string:
            full_json_string = getattr(response, 'output_text', None)
        if not full_json_string:
            try:
                parts = []
                for item in getattr(response, 'output', []) or []:
                    content_list = getattr(item, 'content', None)
                    if isinstance(content_list, list):
                        for c in content_list:
                            t = getattr(c, 'text', None)
                            if t:
                                parts.append(t)
                if parts:
                    full_json_string = "".join(parts)
            except Exception:
                pass
        if not full_json_string:
            raise SkillExtractionError("Réponse OpenAI sans texte de sortie exploitable (extraction compétences).")
        # Récupération de l'usage, s'il est fourni dans la réponse
        usage_info = getattr(response, "usage", None)

        logging.info(f"Appel API OpenAI terminé. Réponse récupérée (longueur: {len(full_json_string)}).")
        if callback:
            callback({"type": "info", "message": "Réception de la réponse OpenAI terminée.", "step": "skill_extract_api"})

        # Sauvegarde du résultat JSON dans le fichier
        try:
            with open(output_json_filename, "w", encoding="utf-8") as f:
                try:
                    parsed_json = json.loads(full_json_string)
                    json.dump(parsed_json, f, ensure_ascii=False, indent=4)
                except json.JSONDecodeError:
                    logging.warning(f"JSON invalide lors du formatage. Sauvegarde brute dans {output_json_filename}.")
                    f.write(full_json_string)
        except IOError as io_err:
            msg = f"Erreur d'écriture lors de la sauvegarde du JSON: {io_err}"
            logging.error(msg, exc_info=True)
            if callback:
                callback({"type": "error", "message": msg, "step": "skill_extract_save"})
            raise SkillExtractionError(msg) from io_err

        logging.info(f"Compétences extraites et sauvegardées dans {output_json_filename}")
        if callback:
            callback({"type": "success", "message": f"Fichier JSON sauvegardé: {os.path.basename(output_json_filename)}", "step": "skill_extract_save"})

        return {"result": full_json_string, "usage": usage_info}

    except SkillExtractionError:
        raise
    except Exception as e:
        msg = f"Erreur lors de l'appel ou du traitement de la réponse OpenAI : {e}"
        logging.error(msg, exc_info=True)
        if callback:
            callback({"type": "error", "message": f"Erreur majeure : {e}", "step": "skill_extract_error"})
        raise SkillExtractionError(msg, original_exception=e) from e

def extraire_competences_depuis_pdf(pdf_path, output_json_filename, openai_key=None, callback=None, pdf_url: str | None = None):
    """
    Extrait toutes les compétences directement à partir d'un PDF via OpenAI Responses.
    Retourne {"result": json_string, "usage": usage_obj}.
    Ajouts: logs détaillés de bout en bout (stratégie, timings, compte de compétences).
    """
    import time

    start_ts = time.monotonic()

    def _progress(msg: str):
        logging.info(msg)
        try:
            if callback:
                callback(msg)
        except Exception:
            # on ne casse pas le flux si le callback échoue
            pass

    api_key = openai_key or current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        msg = "Clé API OpenAI non trouvée dans la configuration."
        logging.error(msg)
        raise SkillExtractionError(msg)

    settings = _get_ocr_settings_safely()
    model_name = (settings.model_extraction if (settings and settings.model_extraction) else current_app.config.get('OPENAI_MODEL_EXTRACTION'))
    _progress(f"[EXTRACTION] Début | modèle='{model_name}' | pdf_url={'oui' if pdf_url else 'non'} | pdf_path='{pdf_path}'")

    try:
        client = OpenAI(api_key=api_key)
        _progress("[EXTRACTION] Client OpenAI initialisé")
    except Exception as e:
        msg = f"Erreur initialisation client OpenAI (PDF): {e}"
        logging.error(msg, exc_info=True)
        raise SkillExtractionError(msg) from e

    if not pdf_url:
        if not pdf_path or not os.path.exists(pdf_path):
            raise SkillExtractionError(f"PDF introuvable: {pdf_path}")
        try:
            pdf_size = os.path.getsize(pdf_path)
        except Exception:
            pdf_size = None
        _progress(f"[EXTRACTION] Fichier local détecté | taille={pdf_size} octets")

    # Prompt et schéma alignés sur la version texte pour garantir le même remplissage des champs
    system_prompt_inline = (
        """Tu es un assistant expert spécialisé dans l'extraction d'informations structurées à partir de documents textuels bruts, en particulier des descriptions de compétences de formation québécoises (souvent issues de PDF de programmes d'études).

Ton objectif principal est d'analyser le document PDF fourni (potentiellement bruité par l'OCR), d'identifier chaque bloc décrivant une compétence unique (généralement introduit par un code alphanumérique comme "Code : XXXX" ou "0XXX"), et d'en extraire méticuleusement les informations suivantes pour CHAQUE compétence trouvée:
1. Le `Code` de la compétence (ex: "02MU", "O1XY").
2. Le `Nom de la compétence` (le titre ou l'énoncé principal, ex: "Adopter un comportement professionnel.").
3. Le `Contexte de réalisation` : extrais toutes les lignes descriptives textuelles trouvées sous ce titre exact. Structure spécifiquement les sous-sections introduites par "À partir :" et "À l’aide :" comme des listes de chaînes de caractères, ET supporte des sous-structures hiérarchiques en représentant le contexte comme une liste d'items `{texte, sous_points}` (où `sous_points` est récursif). Si une sous-section ("À partir de:", "À l'aide de:") est absente, sa valeur peut être `null` ou une liste vide. Si toute la section "Contexte de réalisation" est absente, sa valeur doit être `null`.
4. Les `Critères de performance pour l’ensemble de la compétence` : extrais les lignes descriptives textuelles trouvées sous ce titre exact sous forme de liste de chaînes de caractères. Si la section est absente ou marquée comme non applicable (ex: "S. O."), la valeur du champ doit être `null` ou une liste vide.
5. Les `Éléments` : Identifie chaque élément spécifique de la compétence (souvent numéroté `1.`, `2.`, etc., ou précédé d'une puce). Pour chaque élément, crée un objet contenant deux champs: `element` (la description textuelle de l'élément de compétence spécifique) et `criteres` (une liste de chaînes de caractères contenant les critères de performance associés spécifiquement à cet élément). Si aucun critère n'est listé pour un élément, `criteres` doit être `null` ou une liste vide. Si la section "Éléments" entière est absente, sa valeur doit être `null`.

ATTENTION : Le document peut contenir plusieurs types de compétences (formation générale, formation spécifique, formation complémentaire).
Tu dois EXTRAIRE UNIQUEMENT les compétences de la formation spécifique reliée au programme, et IGNORER celles de la formation générale ou complémentaire.

Nettoie le texte: retire les puces/marqueurs de liste redondants (e, °, +, o, *, - en tête de ligne si déjà listé), les pieds de page récurrents ("Ministère...", "Code de programme XXX"), les numéros de page isolés, et les marqueurs de saut de page. Utilise exclusivement le schéma JSON fourni et ne renvoie aucun texte hors JSON.
"""
    )
    if settings and settings.extraction_prompt:
        system_prompt_inline = settings.extraction_prompt
    json_schema = {
        "type": "object",
        "required": ["competences"],
        "properties": {
            "competences": {
                "type": "array",
                "description": "Liste des objets représentant chaque compétence extraite du document.",
                "items": {
                    "type": "object",
                    "required": [
                        "Code",
                        "Nom de la compétence",
                        "Contexte de réalisation",
                        "Critères de performance pour l’ensemble de la compétence",
                        "Éléments"
                    ],
                    "properties": {
                        "Code": {"type": "string", "description": "Code alphanumérique unique de la compétence (ex: 02MU)."},
                        "Nom de la compétence": {"type": "string", "description": "Le titre ou l'énoncé principal de la compétence."},
                        "Contexte de réalisation": {
                            "type": ["array", "null"],
                            "description": "Structure hiérarchique du contexte (liste d'items récursifs).",
                            "items": {"$ref": "#/definitions/context_item"}
                        },
                        "Critères de performance pour l’ensemble de la compétence": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "Liste des critères généraux."
                        },
                        "Éléments": {
                            "type": ["array", "null"],
                            "description": "Liste des éléments spécifiques décomposant la compétence.",
                            "items": {
                                "type": "object",
                                "required": ["element", "criteres"],
                                "properties": {
                                    "element": {"type": "string", "description": "Description de l'élément de compétence."},
                                    "criteres": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Liste des critères pour cet élément."}
                                },
                                "additionalProperties": False
                            }
                        }
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False,
        "definitions": {
            "context_item": {
                "type": "object",
                "required": ["texte", "sous_points"],
                "properties": {
                    "texte": {"type": "string", "description": "Contenu textuel du point principal ou sous-point."},
                    "sous_points": {"type": ["array", "null"], "description": "Sous-points hiérarchiques.", "items": {"$ref": "#/definitions/context_item"}}
                },
                "additionalProperties": False
            }
        }
    }

    file_id = None
    response = None
    route_used = None
    try:
        req_start_ts = time.monotonic()
        # Construire l'input pour l'appel
        request_input = [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt_inline}]}
        ]
        if pdf_url:
            try:
                route_used = "file_url"
                _progress(f"[EXTRACTION] Appel API via URL de fichier | url='{pdf_url}'")
                request_input.append({
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_url": pdf_url},
                        {"type": "input_text", "text": "Extrais et retourne le JSON strict 'competences'."}
                    ]
                })
            except Exception as e:
                logging.info(f"[EXTRACTION] 'file_url' non supporté ou erreur ({e}). Fallback upload.")
                pdf_url = None

        if not pdf_url:
            route_used = "upload"
            with open(pdf_path, 'rb') as f:
                up = client.files.create(file=f, purpose='user_data')
            file_id = getattr(up, 'id', None)
            _progress(f"[EXTRACTION] Fichier uploadé | file_id='{file_id}'")
            request_input.append({
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": file_id},
                    {"type": "input_text", "text": "Extrais et retourne le JSON strict 'competences'."}
                ]
            })

        request_kwargs = dict(
            model=model_name,
            input=request_input,
            text={"format": {"type": "json_schema", "name": "extraire_competences_en_json", "strict": True, "schema": json_schema}},
            store=True,
            reasoning={"summary": "auto"},
        )

        # --- Streaming ---
        streamed_text = ""
        usage_info = None
        final_response = None
        events_count = 0
        progress_tick = 50  # fréquence d'émission des événements de progression

        try:
            with client.responses.stream(**request_kwargs) as stream:
                reasoning_summary_text = ''
                for event in stream:
                    events_count += 1
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            logging.info(f"[EXTRACTION][stream] delta len={len(delta)} total={len(streamed_text)} type={etype}")
                            # Remonter périodiquement l'avancement en streaming au callback (UI)
                            try:
                                # Toujours pousser un état structuré minimal pour permettre un aperçu en direct
                                if callback:
                                    callback({
                                        'type': 'stream',
                                        'stream_chunk': delta,
                                        'stream_buffer': streamed_text,
                                        'events': events_count
                                    })
                                # Et périodiquement, pousser un message de progression texte (rétro‑compatibilité)
                                if progress_tick and (events_count % progress_tick == 0):
                                    _progress(f"[EXTRACTION][stream] output_text.delta total={len(streamed_text)} chars | events={events_count}")
                            except Exception:
                                pass
                    elif etype.endswith('response.output_item.added') or etype == 'response.output_item.added':
                        try:
                            item = getattr(event, 'item', None)
                            text_val = ''
                            if item:
                                if isinstance(item, dict):
                                    text_val = item.get('text') or ''
                                else:
                                    text_val = getattr(item, 'text', '') or ''
                            if text_val:
                                streamed_text += text_val
                                logging.info(f"[EXTRACTION][stream] item.added len={len(text_val)} total={len(streamed_text)}")
                        except Exception:
                            pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        try:
                            rs_delta = getattr(event, 'delta', '') or ''
                            if rs_delta:
                                reasoning_summary_text += rs_delta
                                if callback:
                                    callback({ 'type': 'reasoning', 'reasoning_summary': reasoning_summary_text })
                        except Exception:
                            pass
                    elif etype.endswith('response.completed') or etype == 'response.completed':
                        logging.info("[EXTRACTION][stream] completed")
                        try:
                            _progress("[EXTRACTION][stream] completed")
                        except Exception:
                            pass
                    elif etype.endswith('response.error') or etype == 'response.error':
                        logging.error(f"[EXTRACTION][stream] error event: {getattr(event, 'error', None)}")
                    else:
                        logging.debug(f"[EXTRACTION][stream] event={etype}")

                final_response = stream.get_final_response()
                usage_info = getattr(final_response, 'usage', None)
                # Dernière remontée du résumé si disponible
                try:
                    if reasoning_summary_text and callback:
                        callback({ 'type': 'reasoning', 'reasoning_summary': reasoning_summary_text })
                except Exception:
                    pass
        except Exception as stream_err:
            logging.warning(f"[EXTRACTION] Streaming non disponible/échoué ({stream_err}). Fallback non-stream.")
            final_response = client.responses.create(**request_kwargs)
            try:
                usage_info = getattr(final_response, 'usage', None)
            except Exception:
                usage_info = None

        req_dur = time.monotonic() - req_start_ts
        rid = getattr(final_response, "id", None)
        status = getattr(final_response, "status", None)
        _progress(f"[EXTRACTION] Réponse finale reçue | route={route_used} | response_id={rid} | status={status} | durée_api={req_dur:.2f}s | events={events_count}")

        # --- Extraction robuste du JSON ---
        json_start_ts = time.monotonic()
        full_json_string = None
        parsed_json = None
        source_method = None

        try:
            parsed_json = getattr(final_response, "output_parsed", None)
            if parsed_json is not None:
                source_method = "output_parsed"
        except Exception:
            parsed_json = None

        if parsed_json is None:
            try:
                full_json_string = getattr(final_response, "output_text", None)
                if full_json_string:
                    source_method = "output_text"
            except Exception:
                full_json_string = None

        if parsed_json is None and not full_json_string and streamed_text:
            full_json_string = streamed_text
            source_method = "stream_buffer"

        if parsed_json is None and not full_json_string:
            try:
                parts = []
                for item in getattr(final_response, 'output', []) or []:
                    content_list = getattr(item, 'content', None)
                    if isinstance(content_list, list):
                        for c in content_list:
                            t = getattr(c, 'text', None)
                            if t:
                                parts.append(t)
                if parts:
                    full_json_string = "".join(parts)
                    source_method = "output[].content[].text"
            except Exception:
                pass

        if parsed_json is None and not full_json_string:
            try:
                for item in getattr(final_response, 'output', []) or []:
                    parsed_candidate = getattr(item, 'parsed', None)
                    if parsed_candidate is not None:
                        parsed_json = parsed_candidate
                        source_method = "output[].parsed"
                        break
            except Exception:
                pass

        if parsed_json is None and not full_json_string:
            raise SkillExtractionError("Réponse OpenAI sans texte de sortie exploitable (PDF).")

        if parsed_json is None:
            try:
                parsed_json = json.loads(full_json_string)
                _progress(f"[EXTRACTION] JSON parsé depuis {source_method} | longueur={len(full_json_string)}")
            except json.JSONDecodeError as e:
                try:
                    with open(output_json_filename, "w", encoding="utf-8") as f:
                        f.write(full_json_string)
                    _progress(f"[EXTRACTION] JSON brut sauvegardé (non valide) dans '{output_json_filename}'")
                except Exception as io_err:
                    logging.error(f"Erreur lors de l'écriture du JSON brut: {io_err}", exc_info=True)
                raise SkillExtractionError(f"JSON invalide renvoyé par le modèle : {e}") from e

        nb_comp = None
        try:
            if isinstance(parsed_json, dict):
                comps = parsed_json.get("competences") or []
                nb_comp = len(comps) if isinstance(comps, list) else None
        except Exception:
            pass

        json_dur = time.monotonic() - json_start_ts
        _progress(f"[EXTRACTION] Méthode d'extraction='{source_method}' | competences={nb_comp} | durée_parse={json_dur:.2f}s")

        io_start_ts = time.monotonic()
        try:
            with open(output_json_filename, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, ensure_ascii=False, indent=4)
            try:
                out_size = os.path.getsize(output_json_filename)
            except Exception:
                out_size = None
            _progress(f"[EXTRACTION] Résultat écrit -> '{output_json_filename}' | taille={out_size} octets")
        except Exception as io_err:
            raise SkillExtractionError(f"Erreur écriture JSON: {io_err}") from io_err
        io_dur = time.monotonic() - io_start_ts

        try:
            if isinstance(usage_info, dict):
                pt = usage_info.get("input_tokens")
                ct = usage_info.get("output_tokens")
            else:
                pt = getattr(usage_info, "input_tokens", None)
                ct = getattr(usage_info, "output_tokens", None)
            _progress(f"[EXTRACTION] Usage tokens | input={pt} | output={ct}")
        except Exception:
            pass

        total_dur = time.monotonic() - start_ts
        _progress(f"[EXTRACTION] Terminé | route={route_used} | competences={nb_comp} | I/O={io_dur:.2f}s | total={total_dur:.2f}s")

        return {"result": json.dumps(parsed_json, ensure_ascii=False), "usage": usage_info}

    except SkillExtractionError:
        # l'erreur a déjà été loggée en amont
        raise
    except Exception as e:
        msg = f"Erreur lors de l'appel OpenAI (PDF): {e}"
        logging.error(msg, exc_info=True)
        raise SkillExtractionError(msg, original_exception=e) from e
    finally:
        # Nettoyage de l'upload si nécessaire
        if file_id:
            try:
                client.files.delete(file_id)
                _progress(f"[EXTRACTION] Nettoyage effectué | file_id supprimé='{file_id}'")
            except Exception as e:
                logging.warning(f"[EXTRACTION] Impossible de supprimer file_id='{file_id}' ({e})")
