import logging
import json
import re
import unicodedata
from typing import Dict, Optional

from celery import shared_task
from openai import OpenAI
from pydantic import BaseModel, Field
import shutil
import subprocess

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    PlanDeCours, PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
    PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations, PlanDeCoursEvaluationsCapacites,
    User, SectionAISettings
)

logger = logging.getLogger(__name__)


class ImportDisponibiliteItem(BaseModel):
    jour_semaine: Optional[str] = None
    plage_horaire: Optional[str] = None
    lieu: Optional[str] = None


class ImportMediagraphieItem(BaseModel):
    reference_bibliographique: Optional[str] = None


class ImportEvaluationCapacite(BaseModel):
    capacite: Optional[str] = None
    ponderation: Optional[str] = None


class ImportEvaluationItem(BaseModel):
    titre_evaluation: Optional[str] = None
    description: Optional[str] = None
    semaine: Optional[int] = None
    capacites: list[ImportEvaluationCapacite] = Field(default_factory=list)


class CalendarEntry(BaseModel):
    semaine: Optional[int] = None
    sujet: Optional[str] = None
    activites: Optional[str] = None
    travaux_hors_classe: Optional[str] = None
    evaluations: Optional[str] = None


class ImportPlanDeCoursResponse(BaseModel):
    presentation_du_cours: Optional[str] = None
    objectif_terminal_du_cours: Optional[str] = None
    organisation_et_methodes: Optional[str] = None
    accomodement: Optional[str] = None
    evaluation_formative_apprentissages: Optional[str] = None
    evaluation_expression_francais: Optional[str] = None
    materiel: Optional[str] = None

    calendriers: list[CalendarEntry] = Field(default_factory=list)

    nom_enseignant: Optional[str] = None
    telephone_enseignant: Optional[str] = None
    courriel_enseignant: Optional[str] = None
    bureau_enseignant: Optional[str] = None

    disponibilites: list[ImportDisponibiliteItem] = Field(default_factory=list)
    mediagraphies: list[ImportMediagraphieItem] = Field(default_factory=list)
    evaluations: list[ImportEvaluationItem] = Field(default_factory=list)
PLAN_DE_COURS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "presentation_du_cours": {"type": ["string", "null"]},
        "objectif_terminal_du_cours": {"type": ["string", "null"]},
        "organisation_et_methodes": {"type": ["string", "null"]},
        "accomodement": {"type": ["string", "null"]},
        "evaluation_formative_apprentissages": {"type": ["string", "null"]},
        "evaluation_expression_francais": {"type": ["string", "null"]},
        "materiel": {"type": ["string", "null"]},
        "calendriers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "semaine": {"type": ["integer", "null"]},
                    "sujet": {"type": ["string", "null"]},
                    "activites": {"type": ["string", "null"]},
                    "travaux_hors_classe": {"type": ["string", "null"]},
                    "evaluations": {"type": ["string", "null"]}
                },
                "required": ["semaine", "sujet", "activites", "travaux_hors_classe", "evaluations"],
                "additionalProperties": False,
            },
        },
        "nom_enseignant": {"type": ["string", "null"]},
        "telephone_enseignant": {"type": ["string", "null"]},
        "courriel_enseignant": {"type": ["string", "null"]},
        "bureau_enseignant": {"type": ["string", "null"]},
        "disponibilites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "jour_semaine": {"type": ["string", "null"]},
                    "plage_horaire": {"type": ["string", "null"]},
                    "lieu": {"type": ["string", "null"]}
                },
                "required": ["jour_semaine", "plage_horaire", "lieu"],
                "additionalProperties": False,
            },
        },
        "mediagraphies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference_bibliographique": {"type": ["string", "null"]}
                },
                "required": ["reference_bibliographique"],
                "additionalProperties": False,
            },
        },
        "evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titre_evaluation": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "semaine": {"type": ["integer", "null"]},
                    "capacites": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "capacite": {"type": ["string", "null"]},
                                "ponderation": {"type": ["string", "null"]},
                            },
                            "required": ["capacite", "ponderation"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["titre_evaluation", "description", "semaine", "capacites"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "presentation_du_cours",
        "objectif_terminal_du_cours",
        "organisation_et_methodes",
        "accomodement",
        "evaluation_formative_apprentissages",
        "evaluation_expression_francais",
        "materiel",
        "calendriers",
        "nom_enseignant",
        "telephone_enseignant",
        "courriel_enseignant",
        "bureau_enseignant",
        "disponibilites",
        "mediagraphies",
        "evaluations",
    ],
    "additionalProperties": False
}



def _normalize_text(s: Optional[str]) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def _build_capacity_index(plan_cadre) -> Dict[str, int]:
    """Build a robust lookup for capacities.

    Keys include:
    - normalized title (capacite)
    - normalized description (description_capacite)
    - combined title + description
    - ordinal aliases based on list order: "capacite 1", "cap 1", "c 1"
    - numeric hints present in the raw title
    """
    name_map: Dict[str, int] = {}
    if not plan_cadre or not getattr(plan_cadre, 'capacites', None):
        return name_map

    capacites = list(plan_cadre.capacites or [])
    for idx, cap in enumerate(capacites, start=1):
        if not cap:
            continue
        title_raw = getattr(cap, 'capacite', '') or ''
        desc_raw = getattr(cap, 'description_capacite', '') or ''
        title = _normalize_text(title_raw)
        desc = _normalize_text(desc_raw)

        if title:
            name_map.setdefault(title, cap.id)
        if desc:
            name_map.setdefault(desc, cap.id)
        if title and desc:
            name_map.setdefault(f"{title} {desc}", cap.id)

        # Ordinal aliases from position
        name_map.setdefault(f"capacite {idx}", cap.id)
        name_map.setdefault(f"cap {idx}", cap.id)
        name_map.setdefault(f"c {idx}", cap.id)

        # Numeric hints present in the raw title itself
        m = re.search(r'(?:\b|^)(\d{1,2})(?:\b|$)', title_raw)
        if m:
            name_map.setdefault(f'capacite {m.group(1)}', cap.id)
            name_map.setdefault(f'cap {m.group(1)}', cap.id)
            name_map.setdefault(f'c {m.group(1)}', cap.id)
    return name_map


def _resolve_capacity_id(name: Optional[str], plan_cadre) -> Optional[int]:
    """Resolve a capacity id from a free-form label like "Capacité 2" or full text.

    Strategy:
    1) direct normalized key
    2) numeric hint (capacite/cap/c <n>)
    3) substring either way
    4) token-overlap (Jaccard) with conservative threshold
    """
    if not name:
        return None
    norm = _normalize_text(name)
    index = _build_capacity_index(plan_cadre)
    if not norm or not index:
        return None

    # 1) direct key
    if norm in index:
        return index[norm]

    # 2) numeric hint
    m = re.search(r'(\d{1,2})', norm)
    if m:
        for prefix in ("capacite", "cap", "c"):
            key = f'{prefix} {m.group(1)}'
            if key in index:
                return index[key]

    # 3) substring either direction
    for k, cap_id in index.items():
        if norm in k or k in norm:
            return cap_id

    # 4) token-overlap fuzzy match (simple Jaccard)
    def tokens(s: str) -> set:
        return set(s.split())

    q_tokens = tokens(norm)
    if not q_tokens:
        return None
    best_id = None
    best_score = 0.0
    for k, cap_id in index.items():
        k_tokens = tokens(k)
        if not k_tokens:
            continue
        inter = len(q_tokens & k_tokens)
        union = len(q_tokens | k_tokens)
        if union == 0:
            continue
        score = inter / union
        if score > best_score:
            best_score = score
            best_id = cap_id
    return best_id if best_score >= 0.5 else None


def _extract_first_parsed(response):
    try:
        outputs = getattr(response, 'output', None) or []
        if isinstance(outputs, dict):
            outputs = [outputs]
        for item in outputs:
            contents = []
            if isinstance(item, dict):
                contents = item.get('content') or []
            else:
                contents = getattr(item, 'content', None) or []
            if isinstance(contents, dict):
                contents = [contents]
            for c in contents:
                if isinstance(c, dict):
                    parsed = c.get('parsed')
                else:
                    parsed = getattr(c, 'parsed', None)
                if parsed is not None:
                    return parsed
    except Exception:
        pass
    return None


def _extract_json_like_text(response) -> Optional[dict]:
    """Conservative fallback: try to parse JSON from text fields.

    Handles shapes like:
    - response.output_text (string JSON)
    - response.text (string JSON)
    - response.output[*].content[*].text (string JSON)
    Returns a dict if JSON-decoding succeeds, else None.
    """
    # 1) Direct fields commonly present in SDKs
    for attr in ("output_text", "text"):
        try:
            txt = getattr(response, attr, None)
            if isinstance(txt, str) and txt.strip():
                return json.loads(txt)
        except Exception:
            pass

    # 2) Scan output -> content -> text
    try:
        outputs = getattr(response, 'output', None) or []
        if isinstance(outputs, dict):
            outputs = [outputs]
        for item in outputs:
            contents = []
            if isinstance(item, dict):
                contents = item.get('content') or []
            else:
                contents = getattr(item, 'content', None) or []
            if isinstance(contents, dict):
                contents = [contents]
            for c in contents:
                try:
                    if isinstance(c, dict):
                        txt = c.get('text')
                    else:
                        txt = getattr(c, 'text', None)
                    if isinstance(txt, str) and txt.strip():
                        return json.loads(txt)
                except Exception:
                    continue
    except Exception:
        pass
    return None


@shared_task(bind=True, name='src.app.tasks.import_plan_de_cours.import_plan_de_cours_task')
def import_plan_de_cours_task(
    self,
    plan_de_cours_id: int,
    doc_text: str,
    ai_model: str,
    user_id: int,
    file_path: Optional[str] = None,
    openai_client_cls=None,
):
    """Celery task: parse DOCX text via OpenAI, update PlanDeCours and return UI payload."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}

        cours = plan.cours
        plan_cadre = cours.plan_cadre if cours else None

        # Avoid SQLAlchemy legacy get(); simple session.get is fine here
        user = db.session.get(User, user_id)
        if not user:
            return {"status": "error", "message": "Utilisateur introuvable."}
        if not user.openai_key:
            return {"status": "error", "message": "Clé OpenAI non configurée."}
        if user.credits is None:
            user.credits = 0.0
            db.session.commit()
        if user.credits <= 0:
            return {"status": "error", "message": "Crédits insuffisants."}

        # Prépare system prompt (SectionAISettings 'plan_de_cours_import')
        sa_impt = SectionAISettings.get_for('plan_de_cours_import')
        sys_prompt = (getattr(sa_impt, 'system_prompt', None) or '').strip()

        self.update_state(state='PROGRESS', meta={'message': "Analyse du .docx en cours..."})

        ClientCls = openai_client_cls or OpenAI
        client = ClientCls(api_key=user.openai_key)

        # Si un chemin de fichier est fourni, tenter l'upload (DOCX -> PDF) vers OpenAI
        file_id = None
        pdf_local_path = None
        if file_path:
            try:
                import os as _os
                upload_path = file_path
                if file_path.lower().endswith('.docx'):
                    # Reuse PDF conversion helper used by plan-cadre import
                    from .import_plan_cadre import _create_pdf_from_text  # local import avoids cycles
                    pdf_path = file_path[:-5] + '.pdf'
                    # 1) Try LibreOffice if available (best fidelity incl. tables)
                    used_soffice = False
                    try:
                        if shutil.which('soffice'):
                            subprocess.run([
                                'soffice', '--headless', '--convert-to', 'pdf', '--outdir', _os.path.dirname(pdf_path), file_path
                            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            used_soffice = _os.path.exists(pdf_path)
                            if used_soffice:
                                try:
                                    from PyPDF2 import PdfReader
                                    with open(pdf_path, 'rb') as pf:
                                        pages = len(PdfReader(pf).pages)
                                    size = _os.stat(pdf_path).st_size if _os.path.exists(pdf_path) else -1
                                    logger.info("[import_plan_de_cours_task] Conversion DOCX→PDF via LibreOffice OK: %s (pages=%d, taille=%d)", pdf_path, pages, size)
                                except Exception:
                                    logger.info("[import_plan_de_cours_task] Conversion DOCX→PDF via LibreOffice OK: %s", pdf_path)
                    except Exception:
                        used_soffice = False
                    if not used_soffice:
                        # 2) Mammoth (DOCX->HTML) + WeasyPrint
                        html = None
                        try:
                            import mammoth
                            with open(file_path, 'rb') as df:
                                res = mammoth.convert_to_html(df)
                                html = res.value
                        except Exception:
                            html = None
                        if html:
                            try:
                                from weasyprint import HTML
                                HTML(string=html).write_pdf(pdf_path)
                                try:
                                    from PyPDF2 import PdfReader
                                    with open(pdf_path, 'rb') as pf:
                                        pages = len(PdfReader(pf).pages)
                                    size = _os.stat(pdf_path).st_size if _os.path.exists(pdf_path) else -1
                                    logger.info("[import_plan_de_cours_task] Conversion DOCX→PDF (HTML) OK: %s (pages=%d, taille=%d)", pdf_path, pages, size)
                                except Exception:
                                    logger.info("[import_plan_de_cours_task] Conversion DOCX→PDF (HTML) OK: %s", pdf_path)
                            except Exception:
                                _create_pdf_from_text(doc_text or 'Document importé', pdf_path)
                                try:
                                    size = _os.stat(pdf_path).st_size if _os.path.exists(pdf_path) else -1
                                    logger.info("[import_plan_de_cours_task] PDF texte créé: %s (taille=%d)", pdf_path, size)
                                except Exception:
                                    logger.info("[import_plan_de_cours_task] PDF texte créé: %s", pdf_path)
                        else:
                            _create_pdf_from_text(doc_text or 'Document importé', pdf_path)
                            try:
                                size = _os.stat(pdf_path).st_size if _os.path.exists(pdf_path) else -1
                                logger.info("[import_plan_de_cours_task] PDF texte créé: %s (taille=%d)", pdf_path, size)
                            except Exception:
                                logger.info("[import_plan_de_cours_task] PDF texte créé: %s", pdf_path)
                    upload_path = pdf_path
                    pdf_local_path = pdf_path if _os.path.exists(pdf_path) else None
                with open(upload_path, 'rb') as f:
                    up = client.files.create(file=f, purpose='user_data')
                    file_id = getattr(up, 'id', None)
                if file_id:
                    try:
                        size = _os.stat(upload_path).st_size if _os.path.exists(upload_path) else -1
                        logger.info("[import_plan_de_cours_task] Upload OpenAI OK file_id=%s (taille=%d)", file_id, size)
                    except Exception:
                        logger.info("[import_plan_de_cours_task] Upload OpenAI OK file_id=%s", file_id)
            except Exception:
                logger.exception("Échec upload fichier vers OpenAI (plan de cours); repli en mode texte brut")
                file_id = None

        # Construire l'input pour Responses API
        if file_id:
            input_blocks = []
            if sys_prompt:
                input_blocks.append({"role": "system", "content": [{"type": "input_text", "text": sys_prompt}]})
            input_blocks.append({
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": file_id},
                ]
            })
        else:
            user_input = (
                "Contexte: cours {code} - {nom}, session {session}.\n"
                "Texte du plan de cours (brut):\n---\n{texte}\n---\n"
            ).format(
                code=getattr(cours, 'code', '') or '',
                nom=getattr(cours, 'nom', '') or '',
                session=plan.session,
                texte=(doc_text or '')[:120000],
            )
            input_blocks = []
            if sys_prompt:
                input_blocks.append({"role": "system", "content": [{"type": "input_text", "text": sys_prompt}]})
            input_blocks.append({"role": "user", "content": [{"type": "input_text", "text": user_input}]})

        # Aligner l'appel OpenAI sur import_grille: streaming + JSON schema strict
        # Construire paramètres text/JSON schema à partir du modèle Pydantic
        schema = PLAN_DE_COURS_JSON_SCHEMA
        # Paramètres text/format
        text_params = {
            "format": {
                "type": "json_schema",
                "name": "plan_de_cours",
                "strict": True,
                "schema": schema,
            }
        }
        # Paramètres de raisonnement depuis SectionAISettings si disponibles
        reasoning_params = {"summary": "auto"}
        try:
            if sa_impt and getattr(sa_impt, 'reasoning_effort', None) in {"minimal", "low", "medium", "high"}:
                reasoning_params["effort"] = sa_impt.reasoning_effort
        except Exception:
            pass
        try:
            if sa_impt and getattr(sa_impt, 'verbosity', None) in {"low", "medium", "high"}:
                text_params["verbosity"] = sa_impt.verbosity
        except Exception:
            pass

        request_kwargs = dict(
            model=ai_model,
            input=input_blocks,
            text=text_params,
            reasoning=reasoning_params,
            tools=[],
            store=True,
        )
        # Décodage conservateur si pas un modèle gpt-5
        if not (isinstance(ai_model, str) and ai_model.startswith("gpt-5")):
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

        # Comptabiliser les coûts
        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        # Résumé du raisonnement (si pas déjà poussé en stream, on garde la dernière valeur)
        rs_text = reasoning_summary_text or ""

        # Essayer de récupérer la sortie structurée
        parsed = None
        try:
            parsed = getattr(response, 'output_parsed', None)
        except Exception:
            parsed = None
        if parsed is None:
            parsed = _extract_first_parsed(response)
        if parsed is None:
            parsed = _extract_json_like_text(response)
        # Si dict -> valider via Pydantic pour logique en aval
        try:
            if isinstance(parsed, dict):
                parsed = ImportPlanDeCoursResponse.model_validate(parsed)
        except Exception:
            pass
        if parsed is None:
            return {"status": "error", "message": "Aucune donnée renvoyée par le modèle."}

        # Snapshot des anciennes données pour l'écran de validation
        old_fields = {
            'presentation_du_cours': plan.presentation_du_cours,
            'objectif_terminal_du_cours': plan.objectif_terminal_du_cours,
            'organisation_et_methodes': plan.organisation_et_methodes,
            'accomodement': plan.accomodement,
            'evaluation_formative_apprentissages': plan.evaluation_formative_apprentissages,
            'evaluation_expression_francais': plan.evaluation_expression_francais,
            'seuil_reussite': getattr(plan, 'seuil_reussite', None),
            'materiel': plan.materiel,
            'nom_enseignant': plan.nom_enseignant,
            'telephone_enseignant': plan.telephone_enseignant,
            'courriel_enseignant': plan.courriel_enseignant,
            'bureau_enseignant': plan.bureau_enseignant,
        }
        old_calendriers = [
            {
                'semaine': c.semaine,
                'sujet': c.sujet,
                'activites': c.activites,
                'travaux_hors_classe': c.travaux_hors_classe,
                'evaluations': c.evaluations,
            } for c in plan.calendriers
        ]
        old_mediagraphies = [
            {
                'reference_bibliographique': m.reference_bibliographique,
            } for m in plan.mediagraphies
        ]
        old_disponibilites = [
            {
                'jour_semaine': d.jour_semaine,
                'plage_horaire': d.plage_horaire,
                'lieu': d.lieu,
            } for d in plan.disponibilites
        ]
        old_evaluations = [
            {
                'id': e.id,
                'titre': e.titre_evaluation,
                'description': e.description,
                'semaine': e.semaine,
                'capacites': [
                    {
                        'capacite_id': c.capacite_id,
                        'capacite': (c.capacite.capacite if c.capacite else None),
                        'ponderation': c.ponderation,
                    } for c in e.capacites
                ]
            } for e in plan.evaluations
        ]

        # Ne pas écraser la BD ici: on prépare seulement un aperçu (preview).
        # Les écritures ne seront appliquées que lors de la confirmation côté UI.
        db.session.commit()  # conserver uniquement la décrémentation des crédits utilisateur

        # Build payload for UI
        payload = {
            'fields': {
                'presentation_du_cours': parsed.presentation_du_cours,
                'objectif_terminal_du_cours': parsed.objectif_terminal_du_cours,
                'organisation_et_methodes': parsed.organisation_et_methodes,
                'accomodement': parsed.accomodement,
                'evaluation_formative_apprentissages': parsed.evaluation_formative_apprentissages,
                'evaluation_expression_francais': parsed.evaluation_expression_francais,
                'seuil_reussite': getattr(plan, 'seuil_reussite', None),
                'materiel': parsed.materiel,
                'nom_enseignant': parsed.nom_enseignant,
                'telephone_enseignant': parsed.telephone_enseignant,
                'courriel_enseignant': parsed.courriel_enseignant,
                'bureau_enseignant': parsed.bureau_enseignant,
            },
            'calendriers': [
                {
                    'semaine': c.semaine,
                    'sujet': c.sujet,
                    'activites': c.activites,
                    'travaux_hors_classe': c.travaux_hors_classe,
                    'evaluations': c.evaluations,
                } for c in (parsed.calendriers or [])
            ],
            'mediagraphies': [
                {'reference_bibliographique': m.reference_bibliographique} for m in (parsed.mediagraphies or [])
            ],
            'disponibilites': [
                {
                    'jour_semaine': d.jour_semaine,
                    'plage_horaire': d.plage_horaire,
                    'lieu': d.lieu,
                } for d in (parsed.disponibilites or [])
            ],
            'evaluations': [
                {
                    'titre': e.titre_evaluation,
                    'description': e.description,
                    'semaine': e.semaine,
                    'capacites': [
                        {
                            'capacite': cap.capacite,
                            'ponderation': cap.ponderation,
                        } for cap in (e.capacites or [])
                    ]
                } for e in (parsed.evaluations or [])
            ],
            # Identifiants utiles pour la notification + lien direct
            'cours_id': plan.cours_id,
            'plan_id': plan.id,
            'session': plan.session,
            # Lien de validation/comparaison standardisé
            'validation_url': f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            # Lien direct possible vers l'affichage du plan de cours (fallback)
            'plan_de_cours_url': f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
        }

        # Injecter les anciennes données pour l'écran de validation/annulation
        payload['old_fields'] = old_fields
        payload['old_calendriers'] = old_calendriers
        payload['old_evaluations'] = old_evaluations
        payload['old_mediagraphies'] = old_mediagraphies
        payload['old_disponibilites'] = old_disponibilites

        # Include local PDF path for diagnostics if available
        if pdf_local_path:
            payload['pdf_local_path'] = pdf_local_path

        if rs_text:
            payload['reasoning_summary'] = rs_text
        return {"status": "success", **payload}

    except Exception as e:
        logger.exception("Erreur dans la tâche import_plan_de_cours_task")
        return {"status": "error", "message": str(e)}
