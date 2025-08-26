# app/tasks/ocr.py
import os
import time
import re
import json
import logging
from typing import List, Optional
from types import SimpleNamespace

# Import your OpenAI client (adjust this import according to your library)
from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

# Import your models – adjust these imports as needed:
from ..models import (
    PlanCadre, GlobalGenerationSettings, Competence, ElementCompetence,
    ElementCompetenceParCours, CoursCorequis, Cours, CoursPrealable,
    PlanCadreSavoirEtre, PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires, PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation, User, Programme
)

from celery import shared_task, group, signature
from src.celery_app import celery  # Your Celery instance (configured with your Flask app)
from src.extensions import db  # Your SQLAlchemy instance
from src.utils.openai_pricing import calculate_call_cost
# Import any helper functions used in your logic
from src.utils import (
    replace_tags_jinja2,
    get_plan_cadre_data,
    determine_base_filename,
    extract_code_from_title,
)
from src.ocr_processing import api_clients, pdf_tools, web_utils
from src.ocr_processing.api_clients import SkillExtractionError
from src.config.constants import *
from flask import current_app
from celery.exceptions import Ignore
from celery import chord

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='app.tasks.ocr.extract_json_competence')
def extract_json_competence(self, competence, download_path_local, txt_output_dir,
                            base_filename_local, openai_key, model="gpt-test"):
    """Extrait les compétences d'un segment PDF et retourne les usages API."""
    section_pdf = os.path.join(
        txt_output_dir, f"{base_filename_local}_{competence['code']}.pdf"
    )
    pdf_tools.extract_pdf_section(
        download_path_local, section_pdf,
        competence["page_debut"], competence["page_fin"]
    )
    text = pdf_tools.convert_pdf_to_txt(section_pdf, txt_output_dir, base_filename_local)
    if not text.strip():
        return {
            "competences": [],
            "code": competence["code"],
            "api_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "model": model,
            },
        }
    response = api_clients.extraire_competences_depuis_txt(text, openai_key, model=model)
    usage = response.get("usage", SimpleNamespace(input_tokens=0, output_tokens=0))
    try:
        parsed = json.loads(response.get("result", ""))
        competences = parsed.get("competences", [])
    except Exception:
        competences = []
    return {
        "competences": competences,
        "code": competence["code"],
        "api_usage": {
            "prompt_tokens": getattr(usage, "input_tokens", 0),
            "completion_tokens": getattr(usage, "output_tokens", 0),
            "model": model,
        },
    }

###############################################################################
# Ancien pipeline (segmentation + sous‑tâches) retiré
###############################################################################

###############################################################################
# Tâche Principale OCR (Refactorisée avec Callback)
###############################################################################
@shared_task(bind=True, name='app.tasks.ocr.process_ocr_task')
def process_ocr_task(self, pdf_source, pdf_title, user_id):
    """
    Tâche principale pour l'OCR :
     - Vérifie utilisateur, configure chemins.
     - Télécharge/Prépare PDF.
     - Lance OCR (via API externe).
     - Effectue une extraction directe du PDF complet (pas de segmentation).
     - Met à jour l'état de progression et retourne le résultat final directement.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Démarrage tâche principale process_ocr_task...")

    def update_progress(stage, message, progress, details=None):
        meta = {
            'step': stage,
            'message': message,
            'progress': progress,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title
        }
        if details:
            meta['details'] = details
        try:
            self.update_state(state='PROGRESS', meta=meta)
            logger.debug(f"[{task_id}] State updated to PROGRESS: {stage} - {progress}%")
        except Exception as update_err:
            logger.error(f"[{task_id}] Failed to update Celery state: {update_err}")
            
    update_progress("Initialisation", "Démarrage de la tâche...", 0)
    logger.info(f"[{task_id}] Traitement OCR pour: {pdf_title} ({pdf_source}) par user_id: {user_id}")
    openai_key = None
    user_credits_initial = None
    pdf_output_dir = None
    txt_output_dir = None
    base_filename_local = None
    download_path_local = None
    ocr_markdown_path_local = None
    competences_pages = []
    segmentation_usage_dict = None

    try:
        logger.info(f"[{task_id}] Vérification utilisateur et crédits...")
        try:
            user_data = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
            if not user_data:
                raise ValueError(f"Utilisateur {user_id} introuvable.")
            openai_key = user_data.openai_key
            user_credits_initial = user_data.credits
            if not openai_key:
                raise ValueError(f"Aucune clé OpenAI configurée pour l'utilisateur {user_id}.")
            if user_credits_initial is None or user_credits_initial <= 0:
                logger.warning(f"[{task_id}] Crédits initiaux insuffisants ou invalides ({user_credits_initial}) pour {user_id}.")
            logger.info(f"[{task_id}] Utilisateur {user_id} OK. Crédits initiaux: {user_credits_initial}. Clé API présente.")
        except Exception as db_err:
            logger.critical(f"[{task_id}] Erreur DB récupération utilisateur {user_id}: {db_err}", exc_info=True)
            raise RuntimeError(f"Erreur DB utilisateur: {db_err}")
            
        logger.info(f"[{task_id}] Configuration des chemins...")
        try:
            pdf_output_dir = current_app.config.get('PDF_OUTPUT_DIR', 'pdfs_downloaded')
            txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR', 'txt_outputs')
            if not txt_output_dir:
                raise ValueError("TXT_OUTPUT_DIR n'est pas configuré dans l'application Flask.")
            os.makedirs(pdf_output_dir, exist_ok=True)
            os.makedirs(txt_output_dir, exist_ok=True)
            logger.info(f"[{task_id}] Répertoires OK: PDF='{pdf_output_dir}', TXT='{txt_output_dir}'")
        except Exception as config_err:
            logger.critical(f"[{task_id}] Erreur config/création répertoires: {config_err}", exc_info=True)
            raise RuntimeError(f"Erreur configuration: {config_err}")
            
        update_progress("Détermination", "Étape 0/5 - Nom de fichier", 5)
        logger.info(f"[{task_id}] Étape 0: Détermination nom de fichier...")
        programme_code = extract_code_from_title(pdf_title)
        base_filename_local = determine_base_filename(programme_code, pdf_title)
        if not base_filename_local:
            raise ValueError(f"Impossible de déterminer nom de fichier base pour: {pdf_title}")
        logger.info(f"[{task_id}] Nom fichier base: {base_filename_local}")
        
        # Mettre à jour l'état avec le nom de fichier de base
        self.update_state(state='PROGRESS', meta={
            'step': 'Détermination',
            'message': "Nom fichier déterminé",
            'progress': 10,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local
        })
        
        update_progress("PDF", "Étape 1/5 - Préparation PDF", 15)
        logger.info(f"[{task_id}] Étape 1: Gestion PDF source...")
        if pdf_source.startswith('http://') or pdf_source.startswith('https://'):
            logger.info(f"[{task_id}] Téléchargement URL: {pdf_source}")
            download_path_local = web_utils.telecharger_pdf(pdf_source, pdf_output_dir)
            if not download_path_local or not os.path.exists(download_path_local):
                raise RuntimeError(f"Échec téléchargement ou chemin invalide: {pdf_source} -> {download_path_local}")
            logger.info(f"[{task_id}] PDF téléchargé: {download_path_local}")
        elif os.path.exists(pdf_source):
            target_filename = base_filename_local + ".pdf"
            download_path_local = os.path.join(pdf_output_dir, target_filename)
            if os.path.abspath(pdf_source) != os.path.abspath(download_path_local):
                import shutil
                shutil.copy2(pdf_source, download_path_local)
                logger.info(f"[{task_id}] Fichier local copié: {download_path_local}")
            else:
                logger.info(f"[{task_id}] Utilisation fichier local existant: {download_path_local}")
        else:
            raise FileNotFoundError(f"Source PDF invalide/non trouvée: {pdf_source}")
            
        # Mettre à jour l'état avec les chemins de fichiers
        self.update_state(state='PROGRESS', meta={
            'step': 'PDF',
            'message': "PDF prêt",
            'progress': 25,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local
        })
        
        # Extraction directe: envoyer le PDF complet à OpenAI pour obtenir le JSON des compétences
        update_progress("Extraction IA", "Analyse du PDF complet via OpenAI...", 40)
        logger.info(f"[{task_id}] Appel extraire_competences_depuis_pdf (model: {current_app.config.get('OPENAI_MODEL_EXTRACTION')})")
        json_output_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences.json")
        try:
            # Callback de streaming pour exposer les événements côté UI (SSE)
            def stream_callback(msg):
                try:
                    # Accepte soit une chaîne (rétro‑compat), soit un dict structuré
                    meta_update = {
                        'step': 'Extraction IA',
                        'task_id': task_id,
                        'pdf_source': pdf_source,
                        'pdf_title': pdf_title,
                        'base_filename': base_filename_local,
                        'download_path': download_path_local
                    }
                    total_chars = None
                    stream_chunk = None
                    stream_buffer = None
                    if isinstance(msg, dict):
                        stream_chunk = msg.get('stream_chunk')
                        stream_buffer = msg.get('stream_buffer')
                        reasoning_summary = msg.get('reasoning_summary')
                        # Essayez d'inférer total à partir du buffer
                        try:
                            if isinstance(stream_buffer, str):
                                total_chars = len(stream_buffer)
                        except Exception:
                            total_chars = None
                        # Propager dans le meta pour l'UI (comme plan‑cadre)
                        if stream_chunk is not None:
                            meta_update['stream_chunk'] = stream_chunk
                        if stream_buffer is not None:
                            meta_update['stream_buffer'] = stream_buffer
                        if reasoning_summary:
                            meta_update['reasoning_summary'] = reasoning_summary
                        # Conserver aussi un détail brut lisible
                        meta_update['details'] = f"[stream] total={total_chars or 'n/a'}"
                        dyn_message = f"Streaming ({total_chars} chars)" if isinstance(total_chars, int) else "Streaming..."
                    else:
                        # Ancien format: chaîne de log
                        s = str(msg)
                        m = re.search(r"total=(\d+)", s)
                        if m:
                            total_chars = int(m.group(1))
                        meta_update['details'] = s[:5000]
                        dyn_message = f"Streaming ({total_chars} chars)" if isinstance(total_chars, int) else "Streaming..."

                    # Progression basée sur total
                    progress_val = 50
                    if isinstance(total_chars, int):
                        target = 80000
                        pct = min(1.0, max(0.0, total_chars / float(target)))
                        progress_val = int(50 + pct * 45)

                    meta_update['message'] = dyn_message
                    meta_update['progress'] = progress_val

                    self.update_state(state='PROGRESS', meta=meta_update)
                except Exception:
                    pass

            # Passer aussi l'URL directe si disponible pour éviter l'upload
            pdf_url_arg = pdf_source if (isinstance(pdf_source, str) and (pdf_source.startswith('http://') or pdf_source.startswith('https://'))) else None
            extraction_output = api_clients.extraire_competences_depuis_pdf(
                download_path_local,
                json_output_path,
                openai_key,
                callback=stream_callback,
                pdf_url=pdf_url_arg
            )
        except Exception as e:
            logger.error(f"[{task_id}] Échec extraction depuis PDF: {e}", exc_info=True)
            final_meta = {
                'task_id': task_id,
                'final_status': 'FAILURE',
                'message': f"Erreur extraction PDF: {e}",
                'progress': 100,
                'step': 'Erreur Extraction',
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local
            }
            # Marquer SUCCESS côté Celery pour éviter les soucis de sérialisation d'exception,
            # mais indiquer 'final_status' = 'FAILURE' dans le meta
            self.update_state(state='SUCCESS', meta=final_meta)
            return final_meta

        # Point de contrôle: nous avons une réponse de l'API
        try:
            output_preview_len = len(extraction_output.get('result', '')) if isinstance(extraction_output, dict) else -1
            logger.info(f"[{task_id}] Réponse OpenAI reçue (aperçu longueur={output_preview_len}).")
        except Exception:
            logger.info(f"[{task_id}] Réponse OpenAI reçue (aperçu longueur indisponible).")

        # Mettre à jour l'état pour refléter la réception de la réponse
        try:
            self.update_state(state='PROGRESS', meta={
                'step': 'Post-Extraction',
                'message': "Réponse OpenAI reçue, post-traitement...",
                'progress': 80,
                'task_id': task_id,
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local,
                'json_output_path': json_output_path
            })
        except Exception as upd_err:
            logger.warning(f"[{task_id}] Impossible de mettre à jour l'état PROGRESS(80): {upd_err}")

        # Compter les compétences
        competences_count = 0
        try:
            parsed = json.loads(extraction_output.get('result', '{}'))
            if isinstance(parsed, dict):
                competences_count = len(parsed.get('competences', []) or [])
        except Exception:
            pass

        # Calcul du coût (si usage présent)
        usage = extraction_output.get('usage') if isinstance(extraction_output, dict) else None
        prompt_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
        completion_tokens = getattr(usage, 'output_tokens', 0) if usage else 0
        model_extraction = current_app.config.get('OPENAI_MODEL_EXTRACTION')
        try:
            total_cost = calculate_call_cost(prompt_tokens, completion_tokens, model_extraction)
        except Exception:
            total_cost = 0.0

        # Mettre à jour crédits utilisateur si possible
        try:
            current_user_credits = db.session.query(User.credits).filter_by(id=user_id).scalar()
            if current_user_credits is not None and total_cost > 0 and current_user_credits >= total_cost:
                new_credits = current_user_credits - total_cost
                db.session.execute(text("UPDATE User SET credits = :credits WHERE id = :uid"), {"credits": new_credits, "uid": user_id})
                db.session.commit()
        except Exception as credit_err:
            logger.warning(f"[{task_id}] Échec MAJ crédits: {credit_err}")

        # Final
        final_meta = {
            'task_id': task_id,
            'final_status': 'SUCCESS',
            'message': f"Traitement OCR terminé. {competences_count} compétence(s) extraite(s).",
            'competences_count': competences_count,
            'progress': 100,
            'step': 'Terminé (Extraction Directe)',
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local,
            'json_output_path': json_output_path
        }
        self.update_state(state='SUCCESS', meta=final_meta)
        return final_meta

    except Exception as e:
        logger.critical(f"[{task_id}] Erreur majeure inattendue dans process_ocr_task (avant lancement callback): {e}", exc_info=True)
        final_status_internal = "FAILURE"
        error_message = f"Erreur inattendue (avant callback): {str(e)}"
        try:
            db.session.rollback()
            logger.info(f"[{task_id}] Rollback BDD effectué suite à l'erreur.")
        except Exception as rb_err:
            logger.error(f"[{task_id}] Erreur lors du rollback BDD: {rb_err}", exc_info=True)
        final_meta = {
            'task_id': task_id,
            'final_status': final_status_internal,
            'error': error_message,
            'message': error_message,
            'progress': 100,
            'step': 'Erreur Initiale',
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local if base_filename_local else None,
            'download_path': download_path_local if download_path_local else None,
            'ocr_markdown_path': ocr_markdown_path_local if ocr_markdown_path_local else None
        }
        logger.info(f"[{task_id}] Tentative de mise à jour finale de l'état Celery vers '{final_status_internal}' (erreur pré-callback)")
        try:
            # On marque SUCCESS côté Celery et encode l'erreur dans meta pour cohérence avec le reste du code
            self.update_state(state="SUCCESS", meta=final_meta)
            logger.info(f"[{task_id}] Mise à jour finale de l'état Celery vers 'SUCCESS' réussie.")
        except Exception as final_update_err:
            logger.error(f"[{task_id}] ÉCHEC CRITIQUE: Impossible de mettre à jour l'état final Celery: {final_update_err}", exc_info=True)
        return final_meta

# --- Simplified PDF import task (no website navigation) ---
@shared_task(bind=True, name='app.tasks.ocr.simple_import_competences_pdf')
def simple_import_competences_pdf(self, programme_id: int, pdf_path: str, user_id: int):
    """Extract competencies from a provided PDF and prepare a validation link.

    - Uses user's OpenAI key
    - Calls api_clients.extraire_competences_depuis_pdf with a streaming callback
    - Saves structured JSON under TXT_OUTPUT_DIR as <base>_competences.json
    - Returns a payload including validation_url for review UI
    """
    task_id = self.request.id
    try:
        from src.app.models import Programme, User
        programme = db.session.get(Programme, programme_id)
        if not programme:
            return {'status': 'error', 'message': 'Programme introuvable'}
        user = db.session.get(User, user_id)
        if not user or not user.openai_key:
            return {'status': 'error', 'message': "Clé OpenAI utilisateur manquante"}

        txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR', 'txt_outputs')
        os.makedirs(txt_output_dir, exist_ok=True)

        # Base filename derived from programme
        prog_code = None
        try:
            lp = getattr(programme, 'liste_programme_ministeriel', None)
            prog_code = getattr(lp, 'code', None)
        except Exception:
            prog_code = None
        base = (prog_code or f"programme_{programme.id}")
        base_filename = f"{base}_{int(time.time())}"
        output_json_filename = os.path.join(txt_output_dir, f"{base_filename}_competences.json")

        # Dédoublonnage et lissage du flux pour éviter les répétitions
        last_msg = { 'text': None, 'ts': 0.0 }
        from time import monotonic
        def callback(msg):
            meta = {'step': 'Extraction IA', 'task_id': task_id}
            # Structured streaming: prefer passing buffers/summaries, suppress noisy text
            if isinstance(msg, dict):
                t = msg.get('type')
                if t == 'stream':
                    # Propager le buffer/last chunk pour affichage live, sans spammer le champ message
                    if 'stream_buffer' in msg:
                        meta['stream_buffer'] = msg['stream_buffer']
                    if 'stream_chunk' in msg:
                        meta['stream_chunk'] = msg['stream_chunk']
                    # Optionnel: progression implicite (la barre se mettra à jour côté UI avec progress/pings)
                    try:
                        self.update_state(state='PROGRESS', meta=meta)
                    except Exception:
                        pass
                    return
                if t == 'reasoning':
                    if 'reasoning_summary' in msg:
                        meta['reasoning_summary'] = msg['reasoning_summary']
                    try:
                        self.update_state(state='PROGRESS', meta=meta)
                    except Exception:
                        pass
                    return
                # Generic structured message: map to message if provided
                if 'message' in msg and msg['message']:
                    meta['message'] = str(msg['message'])
                else:
                    # Avoid emitting placeholder messages repeatedly
                    meta['message'] = ''
            else:
                meta['message'] = str(msg)

            # Dédoublonnage de messages identiques très rapprochés
            try:
                now = monotonic()
                text = meta.get('message') or ''
                if text and text == last_msg['text'] and (now - last_msg['ts']) < 2.0:
                    return
                last_msg['text'] = text
                last_msg['ts'] = now
            except Exception:
                pass

            try:
                self.update_state(state='PROGRESS', meta=meta)
            except Exception:
                pass

        out = api_clients.extraire_competences_depuis_pdf(
            pdf_path=pdf_path,
            output_json_filename=output_json_filename,
            openai_key=user.openai_key,
            callback=callback,
        )
        raw_json = out.get('result') if isinstance(out, dict) else None
        usage = out.get('usage') if isinstance(out, dict) else None

        competences = []
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    competences = parsed.get('competences') or []
            except Exception:
                pass

        return {
            'status': 'success',
            'result': {
                'base_filename': base_filename,
                'competences': competences,
            },
            'usage': {
                'prompt_tokens': getattr(usage, 'input_tokens', None) if usage else None,
                'completion_tokens': getattr(usage, 'output_tokens', None) if usage else None,
            },
            'validation_url': f"/programme/{programme.id}/competences/import/review?task_id={task_id}",
        }
    except Exception as e:
        logger.exception('Erreur simple_import_competences_pdf')
        return {'status': 'error', 'message': str(e)}
