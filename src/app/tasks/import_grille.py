# app/tasks/import_grille.py

# Using the configured Celery app instance is crucial for correct broker connection
from src.celery_app import celery
from openai import OpenAI
import logging

from flask import current_app

logger = logging.getLogger(__name__)

# Define the JSON schema outside the task function for clarity
GRILLE_SCHEMA = {
    "type": "object",
    "required": ["programme", "sessions"],
    "properties": {
        "programme": {
            "type": "string",
            "description": "Nom du programme d'études."
        },
        "sessions": {
            "type": "array",
            "description": "Liste des sessions (semestres ou périodes) incluses dans le programme.",
            "items": {
                "type": "object",
                "required": ["numero_session", "cours"],
                "properties": {
                    "numero_session": {
                        "type": "number",
                        "description": "Numéro de session sous forme d'un chiffre (ex.: 1, 2, 3)."
                    },
                    "cours": {
                        "type": "array",
                        "description": "Liste des cours offerts pendant la session.",
                        "items": {
                            "type": "object",
                            "required": [
                                "code_cours", "titre_cours", "heures_theorie",
                                "heures_labo", "heures_maison", "prerequis", "corequis"
                            ],
                            "properties": {
                                "code_cours": {"type": "string", "description": "Code du cours (ex. 243-1J5-LI)."},
                                "titre_cours": {"type": "string", "description": "Intitulé du cours."},
                                "heures_theorie": {"type": "number", "description": "Nombre d'heures de théorie par semaine."},
                                "heures_labo": {"type": "number", "description": "Nombre d'heures de laboratoire par semaine."},
                                "heures_maison": {"type": "number", "description": "Nombre d'heures de travail à la maison par semaine."},
                                "prerequis": {
                                    "type": "array",
                                    "description": "Liste des cours préalables nécessaires.",
                                    "items": {
                                        "type": "object",
                                        "required": ["code_cours", "pourcentage_minimum"],
                                        "properties": {
                                            "code_cours": {"type": "string", "description": "Code du cours préalable."},
                                            # Use number, default to 0 if not applicable/found
                                            "pourcentage_minimum": {"type": "number", "description": "Note minimale requise pour ce préalable (0 si non spécifié)."}
                                        },
                                        "additionalProperties": False
                                    }
                                },
                                "corequis": {
                                    "type": "array",
                                    "description": "Liste des codes des cours corequis.",
                                    "items": {
                                        "type": "string",
                                        "description": "Code d’un cours corequis."
                                    }
                                }
                            },
                            "additionalProperties": False # Disallow extra fields per course
                        }
                    }
                },
                "additionalProperties": False # Disallow extra fields per session
            }
        }
    },
    "additionalProperties": False # Disallow extra fields at the top level
}


@celery.task(bind=True)
def extract_grille_from_pdf_task(self, pdf_path, model=None, openai_key=None):
    """
    Tâche Celery qui :
     1. Charge un fichier PDF via OpenAI.
     2. Utilise client.responses.create() pour extraire la grille de cours
        au format JSON selon un schéma spécifié.

    :param pdf_path: Chemin vers le fichier PDF à traiter.
    :param model: Modèle OpenAI à utiliser.
    :param openai_key: Clé API OpenAI de l'utilisateur.
    :return: Dictionnaire avec le résultat ou un message d'erreur.
    """
    task_id = self.request.id
    if model is None:
        model = current_app.config.get("OPENAI_MODEL_EXTRACTION")
    logger.info(f"[{task_id}] Starting task for PDF: {pdf_path} (model: {model})")

    if not openai_key:
        logger.error(f"[{task_id}] Missing OpenAI API Key.")
        # Fail the task if the key is missing
        # self.update_state(state='FAILURE', meta={'exc_type': 'ValueError', 'exc_message': 'Missing API Key'})
        # raise ValueError("Missing OpenAI API Key")
        return {"status": "error", "message": "Clé API OpenAI manquante."}

    try:
        # Instanciation du client OpenAI
        client = OpenAI(api_key=openai_key)

        logger.info(f"[{task_id}] Uploading PDF file from {pdf_path}")
        # Chargement du fichier PDF dans OpenAI
        with open(pdf_path, "rb") as f:
            file_response = client.files.create(
                file=f,
                purpose="user_data"
            )
        logger.info(f"[{task_id}] File uploaded, file_id: {file_response.id}")

        # Préparation du prompt textuel
        prompt_text = (
            "Vous êtes un assistant spécialisé dans l’extraction structurée de données à partir de documents académiques.\n\n"
            "Votre tâche est d’extraire uniquement les cours de la formation spécifique présents dans le document fourni, "
            "et de les organiser selon le schéma JSON strict 'grille_de_cours' fourni.\n\n"
            "🔒 Contraintes obligatoires :\n"
            "- Respectez strictement le schéma JSON fourni. Aucune propriété additionnelle ou omission ne sera tolérée.\n"
            "- Tous les champs requis doivent être présents et respecter leur type (chaîne, nombre, tableau, etc.).\n"
            "- La sortie doit être un objet JSON valide, correspondant à la structure exacte attendue.\n"
            "- Ne produisez aucun texte explicatif ou commentaire en dehors du JSON.\n"
            "- Lorsqu’un cours présente un format abrégé comme 2-3-2, il représente : 2 heures de théorie, 3 heures de laboratoire, 2 heures de travail à la maison. Décomposez ces valeurs dans les champs correspondants.\n\n"
            "🧠 Règles d’interprétation spécifiques :\n"
            "- Les corequis sont généralement indiqués au-dessus ou à côté du nom du cours correspondant. Associez-les correctement (inclure seulement les codes de cours corequis).\n"
            "- Ignorez toute occurrence de la mention « (ASP) » dans les titres de cours.\n"
            "- N’incluez aucun cours de formation générale (ex: Éducation Physique, Anglais, Philosophie, Français) ou complémentaire.\n"
            "- Si un prérequis a une note minimale spécifiée (ex: '60%'), extrayez cette valeur numérique pour 'pourcentage_minimum', sinon mettez 0.\n"
            "- Extrayez le nom du programme et structurez les cours par session comme indiqué dans le document."
        )

        logger.info(f"[{task_id}] Calling OpenAI responses.create API, model: {model}")
        # Appel de l'API responses avec le fichier et un prompt textuel.
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": file_response.id # CORRECTED: file_id is direct key
                        },
                        {
                            "type": "input_text",
                            "text": prompt_text
                        }
                    ]
                }
            ],
            # Define the expected output structure and constraints
            text={
                "format": {
                    "type": "json_schema",
                    "name": "grille_de_cours", # Must match the name in the schema itself if relevant
                    "strict": True, # Enforce strict adherence
                    "schema": GRILLE_SCHEMA
                }
            },
            # Parameters to control generation
            temperature=0.1, # Lower temperature for more deterministic output
            max_output_tokens=4096, # Adjust as needed based on typical output size
            top_p=1,
            store=True # Store the interaction if needed for review
            # 'reasoning': {}, # Optional: Add reasoning instructions if needed
            # 'tools': [], # Optional: Add tools if needed
        )

        logger.info(f"[{task_id}] OpenAI response received successfully.")

        # Consider adding validation here to ensure output_text is valid JSON
        # import json
        # try:
        #     json.loads(response.output_text)
        #     logger.info(f"[{task_id}] Output is valid JSON.")
        # except json.JSONDecodeError:
        #     logger.error(f"[{task_id}] Output is NOT valid JSON: {response.output_text}")
        #     # Handle invalid JSON case

        # Clean up the uploaded file from OpenAI storage (optional but good practice)
        try:
            logger.info(f"[{task_id}] Deleting uploaded file: {file_response.id}")
            client.files.delete(file_response.id)
            logger.info(f"[{task_id}] Successfully deleted file: {file_response.id}")
        except Exception as delete_err:
            # Log deletion error but don't fail the main task because of it
            logger.warning(f"[{task_id}] Failed to delete file {file_response.id}: {delete_err}")


        return {
            "status": "success",
            "result": response.output_text, # This should be the JSON string
            "usage": {
                "input_tokens": getattr(response.usage, 'input_tokens', 0),
                "output_tokens": getattr(response.usage, 'output_tokens', 0)
            },
            # Page standard de validation/confirmation de l'import
            "validation_url": f"/confirm_grille_import/{task_id}"
        }

    except Exception as e:
        # Log the full error and traceback
        logger.error(f"[{task_id}] Error in extract_grille_from_pdf_task: {e}", exc_info=True)

        # Optionally update Celery task state to FAILURE
        # self.update_state(state='FAILURE', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})

        # Return error status
        # Check if the error is from OpenAI API and try to extract more details
        error_message = str(e)
        if hasattr(e, 'message'): # Handle potential OpenAI specific error structure
            error_message = e.message
        elif hasattr(e, 'response') and hasattr(e.response, 'text'):
             error_message = f"{str(e)} - Response: {e.response.text}"

        return {"status": "error", "message": error_message}
