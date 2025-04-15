# -*- coding: utf-8 -*-
# api_clients.py
from flask import current_app
import logging
import json

from mistralai import Mistral
from openai import OpenAI
import os # Ajout de os pour manipuler les chemins

# === DÉFINIR L'EXCEPTION PERSONNALISÉE ===
class SkillExtractionError(Exception):
    """Exception spécifique pour les erreurs lors de l'extraction des compétences."""
    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.original_exception = original_exception
# =========================================


# --- Fonction perform_ocr_and_save (Garder `print` pour debug console si désiré) ---
def perform_ocr_and_save(pdf_url, output_markdown_filename):
    """Appelle l'API OCR de Mistral et sauvegarde le résultat en Markdown."""
    # --- Initialize client inside the function ---
    api_key = current_app.config.get('MISTRAL_API_KEY')
    if not api_key:
        logging.error("Clé API Mistral non trouvée dans la configuration. Impossible d'effectuer l'OCR.")
        print("Erreur: Clé API Mistral non configurée.")
        return False
    try:
        mistral_client = Mistral(api_key=api_key)
        logging.info("Client Mistral initialisé pour perform_ocr_and_save.")
    except Exception as e:
        logging.error(f"Erreur initialisation client Mistral dans perform_ocr_and_save: {e}")
        return False
    # --- End initialization ---

    logging.info(f"Appel de l'API OCR Mistral pour l'URL: {pdf_url}")
    print("Appel de l'API OCR Mistral...") # Pour console serveur
    try:
        ocr_response = mistral_client.ocr.process(
            model=current_app.config.get('MISTRAL_MODEL_OCR'),
            document={"type": "document_url", "document_url": pdf_url},
            # timeout=180 # Optionnel
        )

        if ocr_response and hasattr(ocr_response, 'pages') and ocr_response.pages:
            logging.info(f"OCR réussi. {len(ocr_response.pages)} pages traitées.")
            with open(output_markdown_filename, "wt", encoding="utf-8") as f:
                for i, page in enumerate(ocr_response.pages):
                    page_num = i + 1
                    f.write(f"## --- Page {page_num} ---\n\n")
                    if hasattr(page, 'markdown') and page.markdown:
                        f.write(page.markdown.strip() + "\n\n")
                    else:
                        f.write(f"*[Contenu Markdown non trouvé pour la page {page_num}]*\n\n")
                        logging.warning(f"Contenu Markdown vide pour la page {page_num}.")
            logging.info(f"Résultat OCR sauvegardé dans {output_markdown_filename}")
            print(f"Résultat OCR sauvegardé dans {output_markdown_filename}") # Pour console serveur
            return True
        else:
            logging.error("Réponse OCR invalide ou vide reçue de l'API Mistral.")
            print("Erreur: Réponse OCR invalide ou vide.") # Pour console serveur
            return False
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API OCR Mistral: {e}", exc_info=True)
        print(f"Erreur lors de l'appel OCR: {e}") # Pour console serveur
        return False


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
        response = openai_client.responses.create(
            model=current_app.config.get('OPENAI_MODEL_SECTION'),
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
    Extrait les compétences via API OpenAI (stream).
    Lève SkillExtractionError en cas d'échec.
    """
    # --- Initialize client inside the function ---
    api_key = openai_key
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
    # --- End initialization ---

    # --- Définition Prompt et Schéma ---
    system_prompt_inline = (
        """Tu es un assistant expert spécialisé dans l'extraction d'informations structurées à partir de documents textuels bruts, en particulier des descriptions de compétences de formation québécoises (extraits souvent de PDF de programmes d'études).

    Ton objectif est d'analyser le texte fourni (issu d’un PDF potentiellement bruité par l’OCR ou la conversion) et d'identifier chaque bloc décrivant une compétence unique (souvent signalée par un code alphanumérique, par exemple "Code : XXXX" ou "0XXX"). Pour chaque compétence identifiée, tu dois extraire méticuleusement les informations suivantes :

    1. **Code** : Le code alphanumérique (ex: "02MU", "O1XY").
    2. **Nom de la compétence** : Le titre ou l’énoncé principal (ex: "Adopter un comportement professionnel.").
    3. **Contexte de réalisation** :
       - Extrais l'intégralité du texte sous le titre "Contexte de réalisation" en respectant sa structure hiérarchique sous forme de points et sous-points.
       - Organise ce contenu en une liste d'objets conformes au schéma suivant : chaque objet (défini comme un "context_item") doit contenir :
         - Une clé **texte** regroupant le contenu principal du point.
         - Une clé **sous_points** qui est soit une liste d'objets supplémentaires (ayant la même structure), soit `null` si aucun sous-point n'existe.
       - Si la section "Contexte de réalisation" est absente, la valeur doit être `null`.
    4. **Critères de performance pour l’ensemble de la compétence** :
       - Extrais les lignes descriptives sous ce titre sous forme de liste.
       - Si la section est absente ou indiquée comme non applicable (ex: "S. O."), la valeur doit être `null` ou une liste vide.
    5. **Éléments** :
       - Identifie chaque élément (souvent numéroté ou précédé d’une puce) et, pour chacun, crée un objet contenant :
         - **element** : la description textuelle de l’élément,
         - **criteres** : une liste des critères de performance associés, extraits immédiatement après la description de l’élément.
       - Si aucun critère n’est listé pour un élément, la valeur de **criteres** doit être `null` ou une liste vide ; et si la section entière est absente, la valeur doit être `null`.

    Pour tous les champs extraits, nettoie le contenu textuel en supprimant les puces ou marqueurs redondants (par exemple, e, °, +, o, *), les pieds de page récurrents ("Ministère...", "Code de programme XXX"), les numéros de page isolés et les marqueurs de saut de page ("=== PAGE BREAK ==="), tout en préservant l'intégralité du sens.

    IMPORTANT : Continue l'extraction et ne termine ta réponse que lorsque l'intégralité du texte a été analysée et que toutes les compétences ont été extraites."""
    )

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
                        "Code": {
                            "type": "string",
                            "description": "Code alphanumérique unique de la compétence (ex: 02MU)."
                        },
                        "Nom de la compétence": {
                            "type": "string",
                            "description": "Le titre ou l'énoncé principal de la compétence."
                        },
                        "Contexte de réalisation": {
                            "type": ["array", "null"],
                            "description": "Représente la structure hiérarchique du 'Contexte de réalisation' sous forme de liste imbriquée. Null si la section est absente.",
                            "items": {"$ref": "#/definitions/context_item"}
                        },
                        "Critères de performance pour l’ensemble de la compétence": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "Liste des critères généraux. Null ou vide si section absente ou 'S.O.'."
                        },
                        "Éléments": {
                            "type": ["array", "null"],
                            "description": "Liste des éléments spécifiques décomposant la compétence. Null si section absente.",
                            "items": {
                                "type": "object",
                                "required": ["element", "criteres"],
                                "properties": {
                                    "element": {
                                        "type": "string",
                                        "description": "Description de l'élément de compétence spécifique."
                                    },
                                    "criteres": {
                                        "type": ["array", "null"],
                                        "items": {"type": "string"},
                                        "description": "Liste des critères associés à cet élément. Null ou vide si absents."
                                    }
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
                    "texte": {
                        "type": "string",
                        "description": "Contenu textuel du point principal ou sous-point."
                    },
                    "sous_points": {
                        "type": ["array", "null"],
                        "description": "Liste des sous-points hiérarchiques (ou null si aucun).",
                        "items": {"$ref": "#/definitions/context_item"}
                    }
                },
                "additionalProperties": False
            }
        }
    }
    # --- Fin Prompt et Schéma ---

    logging.info("Appel API OpenAI (stream) pour extraction compétences...")
    if callback:
        callback({"type": "info", "message": "Début de l'extraction des compétences (stream)...", "step": "skill_extract"})

    full_json_string = ""
    final_response = None  # Variable to capture the final response event
    try:
        stream = openai_client.responses.create(
            model=current_app.config.get('OPENAI_MODEL_EXTRACTION'),
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt_inline}]},
                {"role": "user", "content": [{"type": "input_text", "text": text_content}]}
            ],
            text={"format": {"type": "json_schema", "name": "extraire_competences_en_json", "strict": True, "schema": json_schema}},
            reasoning={}, tools=[], tool_choice="none", temperature=0.5, top_p=1, store=True,
            stream=True
        )

        for event in stream:
            event_type = getattr(event, 'type', None)
            if event_type == 'response.output_text.delta':
                delta = getattr(event, 'delta', '')
                if delta:
                    full_json_string += delta
                    if callback:
                        try:
                            callback({"type": "delta", "data": delta})
                        except Exception as cb_err:
                            logging.error(f"Erreur dans la fonction callback: {cb_err}")
            elif event_type == 'response.failed':
                error_info = getattr(event, 'response', {}).get('error', {})
                error_message = error_info.get('message', 'Erreur stream inconnue')
                msg = f"Événement d'erreur reçu pendant le stream OpenAI: {error_message}"
                logging.error(f"{msg} Détails: {error_info}")
                if callback:
                    callback({"type": "error", "message": msg, "details": error_info, "step": "skill_extract_stream"})
                raise SkillExtractionError(msg)
            elif event_type == 'response.completed':
                logging.info("Événement 'response.completed' reçu du stream.")
                final_response = event
                if callback:
                    callback({"type": "info", "message": "Stream OpenAI terminé.", "step": "skill_extract_stream"})

        logging.info(f"Stream terminé. JSON complet assemblé (longueur: {len(full_json_string)}).")
        if callback:
            callback({"type": "info", "message": "Traitement du stream terminé. Sauvegarde...", "step": "skill_extract_save"})

        try:
            parsed_json_validation = json.loads(full_json_string)
            if not isinstance(parsed_json_validation, dict) or 'competences' not in parsed_json_validation:
                logging.warning("Le JSON assemblé ne contient pas la clé 'competences' attendue.")
        except json.JSONDecodeError as json_val_err:
            logging.warning(f"Le JSON assemblé (stream) n'était pas valide AVANT sauvegarde: {json_val_err}")

        try:
            with open(output_json_filename, "w", encoding="utf-8") as f:
                try:
                    if 'parsed_json_validation' in locals() and isinstance(parsed_json_validation, dict):
                        json.dump(parsed_json_validation, f, ensure_ascii=False, indent=4)
                    else:
                        parsed_json = json.loads(full_json_string)
                        json.dump(parsed_json, f, ensure_ascii=False, indent=4)
                except json.JSONDecodeError:
                    logging.warning(f"JSON invalide lors de la tentative de formatage. Sauvegarde brute dans {output_json_filename}.")
                    f.write(full_json_string)
        except IOError as io_err:
            msg = f"Erreur d'écriture lors de la sauvegarde du JSON: {io_err}"
            logging.error(msg, exc_info=True)
            if callback:
                callback({"type": "error", "message": msg, "step": "skill_extract_save"})
            raise SkillExtractionError(msg) from io_err

        logging.info(f"Compétences extraites (stream) et sauvegardées dans {output_json_filename}")
        if callback:
            callback({"type": "success", "message": f"Fichier JSON sauvegardé: {os.path.basename(output_json_filename)}", "step": "skill_extract_save"})

        usage_info = getattr(final_response, "usage", None)

        # --- Return both the JSON result and the usage info ---
        return {"result": full_json_string, "usage": usage_info}

    except SkillExtractionError:
        raise
    except Exception as e:
        msg = f"Erreur lors de l'appel ou du traitement du stream OpenAI (extraction): {e}"
        logging.error(msg, exc_info=True)
        if callback:
            callback({"type": "error", "message": f"Erreur majeure lors de l'extraction: {e}", "step": "skill_extract_error"})
        raise SkillExtractionError(msg, original_exception=e) from e
