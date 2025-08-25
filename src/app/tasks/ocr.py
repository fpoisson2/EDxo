# app/tasks/ocr.py
import os
import re
import json
import logging
from typing import List, Optional

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
from src.config.constants import *
from flask import current_app 
from celery.exceptions import Ignore
from celery import chord

logger = logging.getLogger(__name__)

###############################################################################
# Tâche d'Extraction JSON par Compétence (avec logging ajouté)
###############################################################################
@shared_task(bind=True, name='app.tasks.ocr.extract_json_competence')
def extract_json_competence(self, competence, download_path_local, txt_output_dir,
                            base_filename_local, openai_key, model=None):
    """
    Tâche de traitement pour une compétence.
    Extrait et analyse une compétence spécifique à partir d'un PDF.
    """
    task_id = self.request.id
    code_comp = competence.get("code", "NO_CODE")  # Default value
    if model is None:
        model = current_app.config.get('OPENAI_MODEL_EXTRACTION')
    else:
        current_app.config['OPENAI_MODEL_EXTRACTION'] = model
    logger.info(f"[{task_id}/{code_comp}] Démarrage extraction compétence (model: {model}).")
    
    try:
        # Initialisation des variables d'utilisation de l'API
        api_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": model
        }
        
        # Extraction des pages
        page_debut = competence.get("page_debut")
        page_fin = competence.get("page_fin")
        if page_debut is None or page_fin is None:
            raise ValueError(f"Pages début/fin manquantes pour compétence {code_comp}")
            
        logger.debug(f"[{task_id}/{code_comp}] Pages: {page_debut}-{page_fin}")
        
        # Détermination des chemins de fichiers
        pdf_output_dir = current_app.config.get('PDF_OUTPUT_DIR', 'pdfs_downloaded')
        competence_pdf_path = os.path.join(pdf_output_dir, f"{base_filename_local}_competence_{code_comp}.pdf")
        
        logger.info(f"[{task_id}/{code_comp}] Extraction section PDF -> {competence_pdf_path}")
        
        # Extraction de la section du PDF
        extract_success = pdf_tools.extract_pdf_section(download_path_local, competence_pdf_path, page_debut, page_fin)
        if not extract_success:
            raise RuntimeError(f"L'extraction du PDF (pages {page_debut}-{page_fin}) a échoué.")
            
        logger.info(f"[{task_id}/{code_comp}] Section PDF extraite.")
        
        # Conversion PDF -> texte
        competence_txt_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences_{code_comp}.txt")
        logger.info(f"[{task_id}/{code_comp}] Conversion PDF -> TXT -> {competence_txt_path}")
        
        competence_text = pdf_tools.convert_pdf_to_txt(competence_pdf_path, competence_txt_path)
        if not competence_text or not competence_text.strip():
            logger.warning(f"[{task_id}/{code_comp}] Conversion en texte vide ou échouée pour {competence_pdf_path}. Retourne liste vide.")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        logger.info(f"[{task_id}/{code_comp}] Conversion TXT réussie (longueur: {len(competence_text)}).")
        
        # Extraction des compétences via l'API OpenAI
        output_json_filename = os.path.join(txt_output_dir, f"{base_filename_local}_competence_{code_comp}.json")
        logger.info(f"[{task_id}/{code_comp}] Appel OpenAI ({model}) pour extraction -> {output_json_filename}")
        
        try:
            extraction_output = api_clients.extraire_competences_depuis_txt(
                competence_text, output_json_filename
            )
        except Exception as api_err:
            logger.error(f"[{task_id}/{code_comp}] Erreur API OpenAI: {api_err}", exc_info=True)
            raise SkillExtractionError(f"Erreur API OpenAI (extraction comp {code_comp}): {api_err}") from api_err
            
        logger.info(f"[{task_id}/{code_comp}] Appel API OpenAI terminé.")
        
        # Récupération des informations d'utilisation
        if isinstance(extraction_output, dict) and 'usage' in extraction_output:
            usage_info = extraction_output['usage']
            # Utiliser input_tokens pour le prompt et output_tokens pour la completion
            api_usage["prompt_tokens"] = getattr(usage_info, 'input_tokens', 0)
            api_usage["completion_tokens"] = getattr(usage_info, 'output_tokens', 0)
            logger.info(f"[{task_id}/{code_comp}] Usage API enregistré: {api_usage['prompt_tokens']} prompt, {api_usage['completion_tokens']} completion")

        # Vérification et traitement de la réponse
        if not isinstance(extraction_output, dict):
            logger.error(f"[{task_id}/{code_comp}] Retour inattendu de extraire_competences_depuis_txt: {type(extraction_output)}")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        competence_json_str = extraction_output.get("result")
        if not competence_json_str:
            logger.warning(f"[{task_id}/{code_comp}] Résultat 'result' vide ou manquant dans la réponse API OpenAI.")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        logger.info(f"[{task_id}/{code_comp}] Parsing du JSON (longueur: {len(competence_json_str)})...")
        
        try:
            comp_data = json.loads(competence_json_str)
        except json.JSONDecodeError as json_e:
            logger.error(f"[{task_id}/{code_comp}] Erreur parsing JSON: {json_e}. Contenu: {competence_json_str[:500]}...")
            raise RuntimeError(f"Erreur parsing JSON pour compétence {code_comp}: {json_e}") from json_e
            
        logger.info(f"[{task_id}/{code_comp}] Parsing JSON réussi.")
        
        if not isinstance(comp_data, dict):
            logger.error(f"[{task_id}/{code_comp}] Données JSON parsées ne sont pas un dict: {type(comp_data)}")
            return {
                "competences": [],
                "code": code_comp,
                "api_usage": api_usage
            }
            
        competences = comp_data.get("competences", [])
        logger.debug(f"[{task_id}/{code_comp}] Compétences brutes extraites: {len(competences)}")
        
        # Enrichissement des compétences avec le code si nécessaire
        for item in competences:
            if isinstance(item, dict) and not item.get("Code"):
                item["Code"] = code_comp
            elif not isinstance(item, dict):
                logger.warning(f"[{task_id}/{code_comp}] Élément de compétence non-dict ignoré: {item}")
                
        competences = [item for item in competences if isinstance(item, dict)]
        logger.info(f"[{task_id}/{code_comp}] Traitement terminé avec succès. Retourne {len(competences)} compétence(s).")
        
        # On retourne les compétences et les informations d'utilisation
        return {
            "competences": competences,
            "code": code_comp,
            "api_usage": api_usage,
            "pages": {
                "debut": page_debut,
                "fin": page_fin
            }
        }
        
    except Exception as e:
        logger.critical(f"[{task_id}/{code_comp}] Erreur TRES INATTENDUE dans extract_json_competence: {e}", exc_info=True)
        raise e

###############################################################################
# NOUVELLE Tâche de Callback pour l'Agrégation
###############################################################################
@shared_task(bind=True, name='app.tasks.ocr.aggregate_ocr_results_task')
def aggregate_ocr_results_task(self, results_list, original_task_id, json_output_path, base_filename, user_id, user_credits_initial, model_section, model_extraction, segmentation_usage_dict):
    """
    Tâche de callback pour agréger les résultats de l'extraction OCR,
    calculer les coûts et finaliser.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Démarrage agrégation pour tâche originale {original_task_id}. Reçu {len(results_list)} résultats de sous-tâches.")
    
    # Récupérer les informations originales de la tâche principale
    original_info = {}
    try:
        original_task_signature = signature('app.tasks.ocr.process_ocr_task', app=celery)
        original_task_result = original_task_signature.AsyncResult(original_task_id)
        if original_task_result.successful() and isinstance(original_task_result.result, dict):
            # Récupérer les informations importantes de la tâche principale
            original_info = original_task_result.info or {}
            logger.info(f"[{task_id}] Informations récupérées de la tâche originale: {list(original_info.keys())}")
    except Exception as fetch_err:
        logger.warning(f"[{task_id}] Impossible de récupérer les infos de la tâche originale: {fetch_err}")
    
    # Agréger les compétences et les usages
    all_competences = []
    total_extraction_prompt = 0
    total_extraction_completion = 0

    # Parcourir les résultats des sous-tâches
    for subtask_result in results_list:
        if isinstance(subtask_result, dict):
            # Nouveau format qui inclut usage et compétences
            if "competences" in subtask_result:
                all_competences.extend(subtask_result.get("competences", []))
                
                # Agréger les usages API
                api_usage = subtask_result.get("api_usage", {})
                total_extraction_prompt += api_usage.get("prompt_tokens", 0)
                total_extraction_completion += api_usage.get("completion_tokens", 0)
        elif isinstance(subtask_result, list):
            # Ancien format (juste une liste de compétences)
            all_competences.extend(subtask_result)
        else:
            logger.warning(f"[{task_id}] Résultat de sous-tâche inattendu ignoré lors de l'agrégation: {type(subtask_result)}")

    competences_count = len(all_competences)
    logger.info(f"[{task_id}] Agrégation terminée. Total compétences extraites: {competences_count}")

    # Sauvegarde du JSON final
    logger.info(f"[{task_id}] Tentative de sauvegarde du JSON final consolidé vers {json_output_path}")
    final_competences_data = {"competences": all_competences}
    final_json_saved = False
    save_error_msg = None
    
    try:
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(final_competences_data, f, ensure_ascii=False, indent=4)
        final_json_saved = True
        logger.info(f"[{task_id}] JSON final sauvegardé avec {competences_count} compétences.")
    except Exception as save_err:
        logger.error(f"[{task_id}] Erreur lors de la sauvegarde du JSON final ({json_output_path}): {save_err}", exc_info=True)
        save_error_msg = str(save_err)
    
    # Calcul des coûts d'API
    logger.info(f"[{task_id}] Calcul du coût total OpenAI...")
    total_cost = 0.0
    total_usage = {"section": {"prompt_tokens": 0, "completion_tokens": 0},
                   "extraction": {"prompt_tokens": 0, "completion_tokens": 0}}
    
    # Coût de la segmentation
    if segmentation_usage_dict and isinstance(segmentation_usage_dict, dict):
        prompt_tokens_sec = segmentation_usage_dict.get('prompt_tokens', 0)
        completion_tokens_sec = segmentation_usage_dict.get('completion_tokens', 0)
        cost_section = calculate_call_cost(prompt_tokens_sec, completion_tokens_sec, model_section)
        total_cost += cost_section
        total_usage["section"]["prompt_tokens"] = prompt_tokens_sec
        total_usage["section"]["completion_tokens"] = completion_tokens_sec
        logger.info(f"[{task_id}] Coût Segmentation ({model_section}): {cost_section:.6f} (P:{prompt_tokens_sec}, C:{completion_tokens_sec})")
    else:
        logger.warning(f"[{task_id}] Usage pour la segmentation non reçu ou invalide.")
    

    cost_extraction = calculate_call_cost(total_extraction_prompt, total_extraction_completion, model_extraction)
    total_cost += cost_extraction
    total_usage["extraction"]["prompt_tokens"] = total_extraction_prompt
    total_usage["extraction"]["completion_tokens"] = total_extraction_completion
    logger.info(f"[{task_id}] Coût Extraction réel ({model_extraction}): {cost_extraction:.6f} (P:{total_extraction_prompt}, C:{total_extraction_completion})")

    # Mise à jour des crédits utilisateur
    logger.info(f"[{task_id}] Tentative de mise à jour BDD crédits pour user {user_id}...")
    db_update_error_msg = None
    
    try:
        # Obtenir les crédits actuels
        current_user_credits = db.session.query(User.credits).filter_by(id=user_id).scalar()
        
        if current_user_credits is None:
            logger.error(f"[{task_id}] Utilisateur {user_id} non trouvé lors de la MAJ des crédits.")
            db_update_error_msg = "Utilisateur introuvable pour MAJ crédits."
        elif current_user_credits < total_cost:
            logger.warning(f"[{task_id}] Coût ({total_cost:.6f}) dépasse les crédits actuels ({current_user_credits}) de l'utilisateur {user_id}. Crédits non mis à jour négativement.")
        else:
            # Calculer les nouveaux crédits
            new_credits = current_user_credits - total_cost
            
            # Utiliser des valeurs numériques directes (et non des objets datetime)
            from datetime import datetime
            now_str = datetime.now().isoformat()
            
            # Mettre à jour les crédits
            db.session.execute(
                text("UPDATE User SET credits = :credits WHERE id = :uid"),
                {"credits": new_credits, "uid": user_id}
            )
            
            # Enregistrer le changement, mais en utilisant une requête SQL directe avec un timestamp correct
            try:
                db.session.execute(
                    text("INSERT INTO DBChange (timestamp, user_id, operation, table_name, record_id, changes) VALUES (:ts, :uid, :op, :tn, :rid, :ch)"),
                    {
                        "ts": datetime.now(),  # Utiliser un objet datetime directement
                        "uid": user_id,
                        "op": "UPDATE",
                        "tn": "User",
                        "rid": user_id,
                        "ch": json.dumps({
                            "credits": {
                                "old": float(current_user_credits),
                                "new": float(new_credits)
                            }
                        })
                    }
                )
            except Exception as track_err:
                logger.warning(f"[{task_id}] Erreur lors du suivi du changement de crédits: {track_err}")
                
            db.session.commit()
            logger.info(f"[{task_id}] Crédits de l'utilisateur {user_id} mis à jour: {current_user_credits} -> {new_credits}")
    except Exception as db_update_err:
        logger.error(f"[{task_id}] Échec de la mise à jour des crédits pour user {user_id}: {db_update_err}", exc_info=True)
        db.session.rollback()
        db_update_error_msg = str(db_update_err)
    
    # Déterminer le statut final
    final_status = "SUCCESS"
    error_details = []
    
    if not final_json_saved:
        final_status = "FAILURE"
        error_details.append(f"Sauvegarde JSON échouée: {save_error_msg}")
    
    if db_update_error_msg:
        error_details.append(f"MAJ crédits échouée: {db_update_error_msg}")
    
    # Message de résultat
    message = f"Traitement OCR terminé. {competences_count} compétences extraites."
    if error_details:
        message += " Erreurs rencontrées: " + "; ".join(error_details)
    
    if competences_count == 0 and final_status == "SUCCESS":
        message = "Traitement OCR terminé. Aucune compétence extraite ou trouvée."
    
    logger.info(f"[{task_id}] Statut final déterminé: {final_status}")
    
    # Préparer les métadonnées du résultat final
    # Récupérer les informations importantes de la tâche principale
    pdf_source = original_info.get('pdf_source') or getattr(original_task_result, 'args', [None])[0] if hasattr(original_task_result, 'args') else None
    pdf_title = original_info.get('pdf_title') or getattr(original_task_result, 'args', [None, None])[1] if hasattr(original_task_result, 'args') else None
    
    final_result_meta = {
        'task_id': original_task_id,
        'callback_task_id': task_id,
        'final_status': final_status,
        'message': message,
        'json_output_path': json_output_path if final_json_saved else None,
        'competences_count': competences_count,
        'openai_cost': total_cost,
        'usage_details': total_usage,
        'db_update_error': db_update_error_msg,
        'save_error': save_error_msg,
        'progress': 100,
        'step': 'Agrégation Terminée',
        'base_filename': base_filename,
        # Ajouter les informations manquantes
        'pdf_source': pdf_source,
        'pdf_title': pdf_title,
        'ocr_markdown_path': original_info.get('ocr_markdown_path'),
        'download_path': original_info.get('download_path')
    }
    
    # Mise à jour de l'état de la tâche originale
    logger.info(f"[{task_id}] Tentative de mise à jour de l'état de la tâche originale {original_task_id} vers {final_status}")
    try:
        original_task_signature = signature('app.tasks.ocr.process_ocr_task', app=celery)
        original_task_result = original_task_signature.AsyncResult(original_task_id)
        original_task_result.backend.store_result(original_task_id, final_result_meta, 'SUCCESS')
        logger.info(f"[{task_id}] État de la tâche originale {original_task_id} mis à jour vers {final_status}.")
    except Exception as update_orig_err:
        logger.error(f"[{task_id}] Impossible de mettre à jour l'état de la tâche originale {original_task_id}: {update_orig_err}", exc_info=True)
    
    # Mise à jour de l'état de cette tâche
    self.update_state(state=final_status, meta=final_result_meta)
    
    return final_result_meta

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
     - Lance Segmentation (via API OpenAI).
     - Lance un groupe de tâches extract_json_competence en parallèle.
     - LIE une tâche aggregate_ocr_results_task qui s'exécutera APRES le groupe.
     - Se termine (état PROGRESS), le résultat final sera défini par le callback.
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
            def stream_callback(msg: str):
                try:
                    # Extraire un compteur cumulatif du message de log, p.ex. "total=50903"
                    total_chars = None
                    try:
                        m = re.search(r"total=(\d+)", str(msg))
                        if m:
                            total_chars = int(m.group(1))
                    except Exception:
                        total_chars = None

                    # Base: 50% au démarrage du streaming, puis progression jusqu'à ~95%
                    progress_val = 50
                    if isinstance(total_chars, int):
                        # Approximation: considérer terminé à 80 000 (caractères ≈ tokens)
                        target = 80000
                        pct = min(1.0, max(0.0, total_chars / float(target)))
                        progress_val = int(50 + pct * 45)  # 50% -> 95%

                    # Rendre le message variant pour déclencher l'SSE
                    dyn_message = (
                        f"Streaming ({total_chars} chars)" if isinstance(total_chars, int) else "Streaming..."
                    )

                    self.update_state(state='PROGRESS', meta={
                        'step': 'Extraction IA',
                        'message': dyn_message,
                        'details': str(msg)[:5000],
                        'progress': progress_val,
                        'task_id': task_id,
                        'pdf_source': pdf_source,
                        'pdf_title': pdf_title,
                        'base_filename': base_filename_local,
                        'download_path': download_path_local
                    })
                except Exception:
                    # Ne pas interrompre la tâche si un update_state échoue
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

        # --- L'ancienne chaîne OCR + segmentation + sous-tâches est désormais court-circuitée ---

        update_progress("OCR", "Étape 2/5 - OCR en cours...", 30)
        logger.info(f"[{task_id}] Étape 2: Lancement OCR...")
        ocr_markdown_path_local = os.path.join(txt_output_dir, f"{base_filename_local}_ocr.md")
        ocr_input_source = pdf_source if pdf_source.startswith('http') else download_path_local
        logger.info(f"[{task_id}] Appel perform_ocr_and_save: Input='{ocr_input_source}', Output='{ocr_markdown_path_local}'")
        ocr_success = api_clients.perform_ocr_and_save(ocr_input_source, ocr_markdown_path_local)
        if not ocr_success:
            if not os.path.exists(ocr_markdown_path_local) or os.path.getsize(ocr_markdown_path_local) == 0:
                raise RuntimeError("Étape OCR échouée: Fichier Markdown non créé ou vide.")
            else:
                logger.warning(f"[{task_id}] perform_ocr_and_save retourné False mais fichier existe. Poursuite...")
        logger.info(f"[{task_id}] OCR Markdown généré: {ocr_markdown_path_local}")
        
        # Mettre à jour l'état avec le chemin OCR
        self.update_state(state='PROGRESS', meta={
            'step': 'OCR',
            'message': "OCR terminé",
            'progress': 40,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local,
            'ocr_markdown_path': ocr_markdown_path_local
        })
        
        update_progress("Segmentation", "Étape 3/5 - Segmentation...", 45)
        logger.info(f"[{task_id}] Étape 3: Segmentation compétences...")
        model_section = current_app.config.get('OPENAI_MODEL_SECTION')
        try:
            with open(ocr_markdown_path_local, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            if not markdown_content:
                raise ValueError(f"Fichier Markdown OCR vide: {ocr_markdown_path_local}")
            logger.info(f"[{task_id}] Lecture Markdown OK ({len(markdown_content)} chars).")
        except Exception as read_err:
            raise RuntimeError(f"Erreur lecture fichier OCR: {read_err}")
            
        try:
            logger.info(f"[{task_id}] Appel find_competences_pages ({model_section}) avec PDF natif + markdown...")
            segmentation_output = api_clients.find_competences_pages(markdown_content, pdf_path=download_path_local)
            logger.debug(f"[{task_id}] Réponse brute de find_competences_pages: {segmentation_output}")
            
            if isinstance(segmentation_output, dict):
                competences_pages = segmentation_output.get("result", {}).get("competences", [])
                segmentation_usage = segmentation_output.get("usage")
                logger.debug(f"[{task_id}] Usage brut de segmentation: {segmentation_usage}, type: {type(segmentation_usage)}")
                
                # Initialiser la variable même si elle n'est pas définie par la suite
                segmentation_usage_dict = None
                
                if segmentation_usage and hasattr(segmentation_usage, 'input_tokens'):
                    logger.debug(f"[{task_id}] Usage a des attributs input_tokens: {getattr(segmentation_usage, 'input_tokens', 0)}")
                    segmentation_usage_dict = {
                        "prompt_tokens": getattr(segmentation_usage, 'input_tokens', 0),
                        "completion_tokens": getattr(segmentation_usage, 'output_tokens', 0),
                    }
                elif segmentation_usage and hasattr(segmentation_usage, 'prompt_tokens'):
                    logger.debug(f"[{task_id}] Usage a des attributs prompt_tokens: {getattr(segmentation_usage, 'prompt_tokens', 0)}")
                    segmentation_usage_dict = {
                        "prompt_tokens": getattr(segmentation_usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(segmentation_usage, 'completion_tokens', 0),
                    }
                elif isinstance(segmentation_usage, dict):
                    logger.debug(f"[{task_id}] Usage est un dict: {segmentation_usage}")
                    segmentation_usage_dict = segmentation_usage
                else:
                    logger.warning(f"[{task_id}] Format d'usage non reconnu: {segmentation_usage}")
                    # Créer un dictionnaire vide mais valide pour éviter les None
                    segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
                    
                logger.info(f"[{task_id}] Segmentation OK ({len(competences_pages)} compétences trouvées). Usage final: {segmentation_usage_dict}")
            else:
                logger.warning(f"[{task_id}] find_competences_pages retour inattendu: {type(segmentation_output)}")
                competences_pages = []
                segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
        except Exception as seg_err:
            logger.error(f"[{task_id}] Erreur find_competences_pages: {seg_err}", exc_info=True)
            competences_pages = []
            segmentation_usage_dict = {"prompt_tokens": 0, "completion_tokens": 0}
            
        # Mettre à jour l'état avec les résultats de segmentation
        self.update_state(state='PROGRESS', meta={
            'step': 'Segmentation',
            'message': "Segmentation terminée",
            'progress': 50,
            'task_id': task_id,
            'pdf_source': pdf_source,
            'pdf_title': pdf_title,
            'base_filename': base_filename_local,
            'download_path': download_path_local,
            'ocr_markdown_path': ocr_markdown_path_local,
            'competences_count': len(competences_pages)
        })
        
        json_output_path = os.path.join(txt_output_dir, f"{base_filename_local}_competences.json")
        model_extraction = current_app.config.get('OPENAI_MODEL_EXTRACTION')
        
        if competences_pages:
            total_competences = len(competences_pages)
            update_progress("Lancement Extraction", f"Étape 4/5 - Lancement extraction pour {total_competences} compétences...", 55)
            logger.info(f"[{task_id}] Étape 4: Lancement groupe pour {total_competences} compétences...")
            
            extraction_tasks_signatures = [
                extract_json_competence.s(
                    comp,
                    download_path_local,
                    txt_output_dir,
                    base_filename_local,
                    openai_key,
                    model_extraction,
                )
                for comp in competences_pages if comp.get('code') and comp.get('page_debut') is not None
            ]
            
            if not extraction_tasks_signatures:
                logger.warning(f"[{task_id}] Aucune compétence valide à traiter après filtrage.")
                final_status_internal = "SUCCESS"
                message = "Traitement terminé. Aucune compétence valide à extraire."
                final_meta = {
                    'task_id': task_id,
                    'final_status': final_status_internal,
                    'message': message,
                    'competences_count': 0,
                    'progress': 100,
                    'step': 'Terminé (Aucune Compétence Valide)',
                    'pdf_source': pdf_source,
                    'pdf_title': pdf_title,
                    'base_filename': base_filename_local,
                    'download_path': download_path_local,
                    'ocr_markdown_path': ocr_markdown_path_local
                }
                self.update_state(state="SUCCESS", meta=final_meta)
                logger.info(f"[{task_id}] Mise à jour état final: {final_status_internal} (Aucune compétence valide)")
                return final_meta

            # Préparation du callback avec les paramètres requis
            callback_task_signature = aggregate_ocr_results_task.s(
                original_task_id=task_id,
                json_output_path=json_output_path,
                base_filename=base_filename_local,
                user_id=user_id,
                user_credits_initial=user_credits_initial,
                model_section=model_section,
                model_extraction=model_extraction,
                segmentation_usage_dict=segmentation_usage_dict
            )
            
            # Lancer le chord de manière asynchrone
            header = group(extraction_tasks_signatures)
            chord_result = (header | callback_task_signature).apply_async()

            # Mettre à jour l'état final avec toutes les informations importantes
            final_meta = {
                'task_id': chord_result.id,
                'message': "Le workflow a été lancé. Veuillez consulter le statut ultérieurement.",
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local,
                'ocr_markdown_path': ocr_markdown_path_local,
                'competences_count_initial': len(competences_pages),
                'json_output_path': json_output_path,
                'step': 'Traitement Asynchrone',
                'progress': 60
            }
            
            update_progress("Traitement Asynchrone", "Lancement des tâches d'extraction en arrière-plan...", 60)

            # Retourner l'ID du chord et toutes les informations importantes
            return final_meta

        else:
            update_progress("Terminé", "Aucune compétence trouvée", 100)
            logger.warning(f"[{task_id}] Aucune compétence trouvée lors de la segmentation. Traitement terminé.")
            final_status_internal = "SUCCESS"
            message = "Traitement OCR terminé. Aucune compétence trouvée ou extraite."
            final_meta = {
                'task_id': task_id,
                'final_status': final_status_internal,
                'message': message,
                'competences_count': 0,
                'progress': 100,
                'step': 'Terminé (Aucune Compétence)',
                'pdf_source': pdf_source,
                'pdf_title': pdf_title,
                'base_filename': base_filename_local,
                'download_path': download_path_local,
                'ocr_markdown_path': ocr_markdown_path_local
            }
            self.update_state(state="SUCCESS", meta=final_meta)
            logger.info(f"[{task_id}] Mise à jour état final: {final_status_internal} (Aucune compétence)")
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
            self.update_state(state="SUCCESS", meta=final_meta)
            logger.info(f"[{task_id}] Mise à jour finale de l'état Celery vers 'SUCCESS' réussie.")
        except Exception as final_update_err:
            logger.error(f"[{task_id}] ÉCHEC CRITIQUE: Impossible de mettre à jour l'état final Celery: {final_update_err}", exc_info=True)
        return final_meta
