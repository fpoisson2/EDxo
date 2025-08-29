# app/tasks/import_grille.py

# Using the configured Celery app instance is crucial for correct broker connection
from src.celery_app import celery
from openai import OpenAI
import logging

from flask import current_app

logger = logging.getLogger(__name__)

"""
JSON Schema strict pour la sortie "programme_etudes".
Note: cette constante contient UNIQUEMENT le schéma JSON (sans clés 'name'/'strict').
"""
GRILLE_JSON_SCHEMA = {
    "type": "object",
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
                "properties": {
                    "numero_session": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Numéro de session comme entier (ex.: 1, 2, 3)."
                    },
                    "cours": {
                        "type": "array",
                        "description": "Liste des cours offerts pendant la session.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code_cours": {
                                    "type": "string",
                                    "description": "Code du cours (ex.: XXX-YYY-ZZ)."
                                },
                                "titre_cours": {
                                    "type": "string",
                                    "description": "Intitulé du cours."
                                },
                                "heures_theorie": {
                                    "type": "number",
                                    "description": "Nombre d'heures de théorie par semaine."
                                },
                                "heures_labo": {
                                    "type": "number",
                                    "description": "Nombre d'heures de laboratoire par semaine."
                                },
                                "heures_maison": {
                                    "type": "number",
                                    "description": "Nombre d'heures de travail à la maison par semaine."
                                },
                                "prerequis": {
                                    "type": "array",
                                    "description": "Liste des cours préalables nécessaires.",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "code_cours": {
                                                "type": "string",
                                                "description": "Code du cours préalable."
                                            },
                                            "pourcentage_minimum": {
                                                "type": "number",
                                                "description": "Note minimale requise pour ce préalable (0 si non spécifié).",
                                                "default": 0
                                            }
                                        },
                                        "required": [
                                            "code_cours",
                                            "pourcentage_minimum"
                                        ],
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
                            "required": [
                                "code_cours",
                                "titre_cours",
                                "heures_theorie",
                                "heures_labo",
                                "heures_maison",
                                "prerequis",
                                "corequis"
                            ],
                            "additionalProperties": False
                        }
                    }
                },
                "required": [
                    "numero_session",
                    "cours"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "programme",
        "sessions"
    ],
    "additionalProperties": False
}


@celery.task(bind=True)
def extract_grille_from_pdf_task(self, pdf_path, model=None, openai_key=None, programme_id=None):
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
        model = (
            current_app.config.get("OPENAI_MODEL_EXTRACTION")
            or "gpt-5"
        )
    logger.info(f"[{task_id}] Starting task for PDF: {pdf_path} (model: {model})")

    if not openai_key:
        logger.error(f"[{task_id}] Missing OpenAI API Key.")
        return {"status": "error", "message": "Clé API OpenAI manquante."}

    try:
        # Instanciation du client OpenAI
        client = OpenAI(api_key=openai_key)

        logger.info(f"[{task_id}] Uploading PDF file from {pdf_path}")
        # Chargement du fichier PDF dans OpenAI
        file_id = None
        with open(pdf_path, "rb") as f:
            file_response = client.files.create(
                file=f,
                purpose="user_data"
            )
        file_id = getattr(file_response, 'id', None)
        logger.info(f"[{task_id}] File uploaded, file_id: {file_id}")

        # Developer/system prompt content must come from settings only

        logger.info(f"[{task_id}] Calling OpenAI responses.create API, model: {model}")
        # Construire la requête
        logger.info(f"[{task_id}] Preparing OpenAI request for model: {model}")
        # Allow section IA settings for import (grille_import)
        try:
            from src.app.models import SectionAISettings
            sa_imp = SectionAISettings.get_for('grille_import')
        except Exception:
            sa_imp = None
        text_params = {
            "format": {
                "type": "json_schema",
                "name": "programme_etudes",
                "strict": True,
                "schema": GRILLE_JSON_SCHEMA,
            }
        }
        try:
            if sa_imp and getattr(sa_imp, 'verbosity', None) in {"low", "medium", "high"}:
                text_params["verbosity"] = sa_imp.verbosity
        except Exception:
            pass
        reasoning_params = {"summary": "auto"}
        try:
            if sa_imp and getattr(sa_imp, 'reasoning_effort', None) in {"minimal", "low", "medium", "high"}:
                reasoning_params["effort"] = sa_imp.reasoning_effort
        except Exception:
            pass
        # System prompt from SectionAISettings('grille_import') only (no hard-coded default)
        sys_prompt = (getattr(sa_imp, 'system_prompt', None) or '').strip()
        request_kwargs = dict(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": sys_prompt}]},
                {"role": "user", "content": [{"type": "input_file", "file_id": file_response.id}]}
            ],
            text=text_params,
            reasoning=reasoning_params,
            tools=[],
            store=True,
        )
        # Paramètres de décodage (faible variabilité) pour modèles non gpt-5
        if not (isinstance(model, str) and model.startswith("gpt-5")):
            request_kwargs.update({
                "temperature": 0.1,
                "top_p": 1,
            })

        # Appel en streaming pour capturer le texte et le résumé de raisonnement
        self.update_state(state='PROGRESS', meta={'message': "Appel au modèle IA..."})
        streamed_text = ""
        reasoning_summary_text = ""
        response = None
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
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
                        except Exception:
                            pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        try:
                            rs_delta = getattr(event, 'delta', '') or ''
                            if rs_delta:
                                reasoning_summary_text += rs_delta
                                try:
                                    self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    elif etype.endswith('response.completed'):
                        pass
                    elif etype.endswith('response.error'):
                        pass
                response = stream.get_final_response()
        except Exception:
            response = client.responses.create(**request_kwargs)
        logger.info(f"[{task_id}] OpenAI response received successfully.")

        # Nettoyage du fichier chargé (bonnes pratiques)
        try:
            if file_id:
                logger.info(f"[{task_id}] Deleting uploaded file: {file_id}")
                client.files.delete(file_id)
                logger.info(f"[{task_id}] Successfully deleted file: {file_id}")
        except Exception as delete_err:
            logger.warning(f"[{task_id}] Failed to delete file {file_id}: {delete_err}")

        # Préférence: sortie structurée directe
        import json as _json
        parsed_direct = None
        try:
            parsed_direct = getattr(response, 'output_parsed', None)
        except Exception:
            parsed_direct = None

        if parsed_direct is not None:
            try:
                result = {
                    "status": "success",
                    "result": parsed_direct,
                    "usage": {
                        "input_tokens": getattr(response.usage, 'input_tokens', 0),
                        "output_tokens": getattr(response.usage, 'output_tokens', 0),
                    },
                    "validation_url": f"/confirm_grille_import/{task_id}" + (f"?programme_id={programme_id}" if programme_id else ""),
                }
                if reasoning_summary_text:
                    result["reasoning_summary"] = reasoning_summary_text
                return result
            except Exception:
                # Continue vers tentative de parsing texte
                pass

        # Tentative de parsing à partir du texte (avec fallback sur le stream)
        raw_text = getattr(response, 'output_text', '') or ''
        if not raw_text and streamed_text:
            raw_text = streamed_text
        if not raw_text:
            try:
                for out in getattr(response, 'output', []) or []:
                    for c in getattr(out, 'content', []) or []:
                        t = getattr(c, 'text', None)
                        if t:
                            raw_text = t
                            break
                    if raw_text:
                        break
            except Exception:
                raw_text = ''

        def _coerce_json(txt: str):
            s = (txt or '').strip()
            # Retirer d'éventuels fences Markdown
            for fence in ("```json", "```JSON", "```",):
                if s.startswith(fence):
                    s = s[len(fence):].strip()
            if s.endswith("```"):
                s = s[:-3].strip()
            # Essai direct
            try:
                return _json.loads(s)
            except Exception:
                pass
            # Tentative: tronquer jusqu'au dernier '}' équilibré
            start = s.find('{')
            end = s.rfind('}')
            if start != -1 and end != -1 and end > start:
                candidate = s[start:end+1]
                try:
                    return _json.loads(candidate)
                except Exception:
                    pass
            # Échec -> lever
            raise

        try:
            parsed = _coerce_json(raw_text)
            result = {
                "status": "success",
                "result": parsed,
                "usage": {
                    "input_tokens": getattr(response.usage, 'input_tokens', 0),
                    "output_tokens": getattr(response.usage, 'output_tokens', 0),
                },
                "validation_url": f"/confirm_grille_import/{task_id}" + (f"?programme_id={programme_id}" if programme_id else ""),
            }
            if reasoning_summary_text:
                result["reasoning_summary"] = reasoning_summary_text
            return result
        except Exception as parse_err:
            logger.warning(f"[{task_id}] JSON non valide; retour du texte brut (pas de fallback). err={parse_err}")
            result = {
                "status": "success",
                "result": raw_text,
                "usage": {
                    "input_tokens": getattr(response.usage, 'input_tokens', 0),
                    "output_tokens": getattr(response.usage, 'output_tokens', 0),
                },
                "validation_url": f"/confirm_grille_import/{task_id}" + (f"?programme_id={programme_id}" if programme_id else ""),
            }
            if reasoning_summary_text:
                result["reasoning_summary"] = reasoning_summary_text
            return result

    except Exception as e:
        # Log the full error and traceback
        logger.error(f"[{task_id}] Error in extract_grille_from_pdf_task: {e}", exc_info=True)

        # Retour d'erreur
        error_message = str(e)
        if hasattr(e, 'message'):
            error_message = e.message
        elif hasattr(e, 'response') and hasattr(e.response, 'text'):
            error_message = f"{str(e)} - Response: {e.response.text}"

        # Tentative de cleanup si nécessaire
        try:
            if 'file_id' in locals() and file_id:
                logger.info(f"[{task_id}] Cleaning up uploaded file after error: {file_id}")
                client.files.delete(file_id)
        except Exception:
            pass

        return {"status": "error", "message": error_message}
