import logging
import re
import unicodedata
from typing import List, Optional, Tuple

from celery import shared_task
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
from xml.sax.saxutils import escape as xml_escape
from pydantic import BaseModel, Field

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    User,
    PlanCadreImportPromptSettings,
)

logger = logging.getLogger(__name__)


class AIContentDetail(BaseModel):
    texte: Optional[str] = None
    description: Optional[str] = None


class AISavoirFaire(BaseModel):
    texte: Optional[str] = None
    cible: Optional[str] = None
    seuil_reussite: Optional[str] = None


class AICapacite(BaseModel):
    capacite: Optional[str] = None
    description_capacite: Optional[str] = None
    ponderation_min: Optional[int] = None
    ponderation_max: Optional[int] = None
    savoirs_necessaires: List[str] = Field(default_factory=list)
    savoirs_faire: List[AISavoirFaire] = Field(default_factory=list)
    moyens_evaluation: List[str] = Field(default_factory=list)


class ImportPlanCadreResponse(BaseModel):
    # Champs simples
    place_intro: Optional[str] = None
    objectif_terminal: Optional[str] = None
    structure_intro: Optional[str] = None
    structure_activites_theoriques: Optional[str] = None
    structure_activites_pratiques: Optional[str] = None
    structure_activites_prevues: Optional[str] = None
    eval_evaluation_sommative: Optional[str] = None
    eval_nature_evaluations_sommatives: Optional[str] = None
    eval_evaluation_de_la_langue: Optional[str] = None
    eval_evaluation_sommatives_apprentissages: Optional[str] = None

    # Listes avec description
    competences_developpees: List[AIContentDetail] = Field(default_factory=list)
    competences_certifiees: List[AIContentDetail] = Field(default_factory=list)
    cours_corequis: List[AIContentDetail] = Field(default_factory=list)
    cours_prealables: List[AIContentDetail] = Field(default_factory=list)
    cours_relies: List[AIContentDetail] = Field(default_factory=list)
    objets_cibles: List[AIContentDetail] = Field(default_factory=list)

    # Savoir-être
    savoir_etre: List[str] = Field(default_factory=list)

    # Capacités
    capacites: List[AICapacite] = Field(default_factory=list)


def _format_import_prompt(template: str, doc_text: str) -> str:
    """Safely format a user-configurable template that contains JSON braces.
    Only substitute the {doc_text} placeholder; escape all other braces.
    """
    if not isinstance(template, str):
        template = str(template or '')
    # First escape all braces to avoid str.format interpreting JSON examples
    safe = template.replace('{', '{{').replace('}', '}}')
    # Re-enable the {doc_text} placeholder for substitution
    safe = safe.replace('{{doc_text}}', '{doc_text}')
    return safe.format(doc_text=(doc_text or '')[:150000])


def _create_pdf_from_text(text: str, pdf_path: str) -> None:
    """Create a simple PDF containing the provided text.
    Uses ReportLab. Preserves paragraphs and basic line breaks; renders markdown tables as preformatted text.
    """
    try:
        styles = getSampleStyleSheet()
        story = []
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        blocks = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n\n')
        for block in blocks:
            b = block.strip()
            if not b:
                continue
            if b.startswith('TABLE ') or '|' in b and '---' in b:
                story.append(Preformatted(b, styles['Code']))
            else:
                # Escape Paragraph markup and keep single line breaks
                safe = xml_escape(b).replace('\n', '<br/>' )
                story.append(Paragraph(safe, styles['BodyText']))
            story.append(Spacer(1, 6))
        if not story:
            story.append(Paragraph(xml_escape('Document vide'), styles['BodyText']))
        doc.build(story)
    except Exception:
        # As last resort, write a minimal PDF with plain text
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        y = height - 72
        for line in (text or '').splitlines() or ['Document vide']:
            c.drawString(72, y, line[:1000])
            y -= 14
            if y < 72:
                c.showPage()
                y = height - 72
        c.save()


def _sanitize_str(s: Optional[str]) -> Optional[str]:
    """Convert literal escape sequences to real control chars and normalize EOLs.
    - "\\n" or "\\r\\n" -> newline, "\\t" -> tab
    - Normalize CRLF/CR to LF
    - Trim trailing spaces on lines and outer whitespace
    """
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    s = s.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    s = '\n'.join(line.rstrip() for line in s.split('\n'))
    return s.strip()


def _normalize_text(s: Optional[str]) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def _extract_first_parsed(response):
    try:
        outputs = getattr(response, 'output', None) or []
        for item in outputs:
            contents = getattr(item, 'content', None) or []
            for c in contents:
                parsed = getattr(c, 'parsed', None)
                if parsed is not None:
                    return parsed
    except Exception:
        pass
    return None


def _collect_summary(items):
    """Return concatenated summary_text from items."""
    text = ""
    if not items:
        return text
    if not isinstance(items, (list, tuple)):
        items = [items]
    for item in items:
        if getattr(item, "type", "") == "summary_text":
            text += getattr(item, "text", "")
    return text


def _extract_reasoning_summary_from_response(response):
    """Extract reasoning summary from a Responses API result."""
    summary = ""
    if hasattr(response, "reasoning") and response.reasoning:
        for r in response.reasoning:
            summary += _collect_summary(getattr(r, "summary", None))
    if not summary and hasattr(response, "output"):
        for item in getattr(response, "output", []):
            if getattr(item, "type", "") == "reasoning":
                summary += _collect_summary(getattr(item, "summary", None))
    return summary.strip()


# -----------------------------
# Fallback extraction helpers
# -----------------------------
def _find_capacity_block(doc_text: str, cap_index: int) -> Optional[str]:
    """Return the text slice corresponding to a given capacité index (1-based).

    Heuristic: look for 'Capacité <n>' marker; slice until next 'Capacité <n+1>' or next 'Capacité ' or end.
    If specific marker not found, return None.
    """
    try:
        n = int(cap_index)
    except Exception:
        return None
    # Normalize accents/spacing lightly for matching while keeping original for slicing
    hay = doc_text
    # Try several variants for matching "Capacité <n>"
    patterns = [
        rf"Capacit[eé]\s*{n}\s*[:\-]",
        rf"Capacit[eé]\s*{n}\b",
    ]
    start = -1
    for pat in patterns:
        m = re.search(pat, hay, flags=re.IGNORECASE)
        if m:
            start = m.start()
            break
    if start < 0:
        return None
    # End: next capacity marker or section break
    # Prefer the exact next index if present
    next_mark = None
    for pat in [rf"Capacit[eé]\s*{n+1}\b", r"Capacit[eé]\s*\d+\b", r"Partie\s+\d+", r"Comp[eé]tence\s*:"]:
        m = re.search(pat, hay[start+1:], flags=re.IGNORECASE)
        if m:
            pos = start + 1 + m.start()
            if next_mark is None or pos < next_mark:
                next_mark = pos
    end = next_mark if next_mark is not None else len(hay)
    return hay[start:end]


def _split_sentences(text: str) -> List[str]:
    """Very simple sentence splitter suitable for our extracted DOCX text."""
    if not text:
        return []
    # Remove excessive whitespace
    t = re.sub(r"\s+", " ", text).strip()
    if not t:
        return []
    # Split on period, semicolon or newline boundaries
    parts = re.split(r"(?<=[\.!?])\s+|\n+|\r+|;\s+", t)
    # Filter trivial parts
    out = []
    for p in parts:
        s = p.strip()
        if len(s.split()) >= 4:  # at least 4 words
            out.append(s)
    return out


def _fallback_fill_cible_seuil(doc_text: str, parsed: ImportPlanCadreResponse) -> None:
    """If AI missed cible/seuil for savoir_faire, try to infer from doc_text.

    Heuristic mapping by order inside each capacité block: first k sentences are cibles,
    next k sentences are seuils. We stop the block before common markers like 'Moyens'.
    """
    if not doc_text or not parsed or not getattr(parsed, 'capacites', None):
        return
    for cap_idx, cap in enumerate(parsed.capacites, start=1):
        if not cap or not cap.savoirs_faire:
            continue
        # Check if all cible/seuil are already present; if yes, skip
        if any(sf and (sf.cible or sf.seuil_reussite) for sf in cap.savoirs_faire):
            # Partial presence: still try to fill missing ones, continue
            pass
        # Locate block by capacity index if present in label; fallback to enumerated order
        block = None
        # Try to extract the numeric index from the capacity title
        cap_number = None
        if cap.capacite:
            mnum = re.search(r"Capacit[eé]\s*(\d+)", cap.capacite, flags=re.IGNORECASE)
            if mnum:
                try:
                    cap_number = int(mnum.group(1))
                except Exception:
                    cap_number = None
        block = _find_capacity_block(doc_text, cap_number or cap_idx)
        if not block:
            continue
        # Trim after typical trailing sections inside block
        cutoff_markers = [
            r"Moyens d['’]évaluation", r"Moyens d[e']", r"Travaux pratiques", r"Rapport d['’]intégration",
            r"Simulation de scénarios", r"Journaux de maintenance"
        ]
        for pat in cutoff_markers:
            m = re.search(pat, block, flags=re.IGNORECASE)
            if m:
                block = block[:m.start()]
                break
        sentences = _split_sentences(block)
        k = len(cap.savoirs_faire)
        # Remove the header part up to the percentage range, if present
        mperc = re.search(r"\d+\s*%\s*[–\-]\s*\d+\s*%", block)
        if mperc:
            after = block[mperc.end():]
            sentences = _split_sentences(after)
        # Heuristic: need at least 2*k sentences to align
        if len(sentences) < 2 * k:
            continue
        cibles = sentences[:k]
        seuils = sentences[k:2 * k]
        # Assign if missing
        for i, sf in enumerate(cap.savoirs_faire):
            if not sf:
                continue
            if not sf.cible and i < len(cibles):
                sf.cible = cibles[i]
            if not sf.seuil_reussite and i < len(seuils):
                sf.seuil_reussite = seuils[i]


def _heuristic_extract_basic_fields(doc_text: str) -> dict:
    """Extract minimal fields from raw text when AI returns nothing.

    Searches for common French headings and captures paragraphs until the next
    heading-like line. Returns a dict shaped like the preview 'proposed'.
    """
    if not doc_text or not isinstance(doc_text, str):
        return {}

    text = doc_text
    # Common headings -> target keys
    patterns = [
        (r"(?im)^\s*#*\s*Place\s+du\s+cours.*$", 'place_intro'),
        (r"(?im)^\s*#*\s*Objectif\s+terminal.*$", 'objectif_terminal'),
        (r"(?im)^\s*#*\s*Structure.*intro.*$", 'structure_intro'),
        (r"(?im)^\s*#*\s*(Activit[eé]s|Activites)\s+th[eé]oriques.*$", 'structure_activites_theoriques'),
        (r"(?im)^\s*#*\s*(Activit[eé]s|Activites)\s+pratiques.*$", 'structure_activites_pratiques'),
        (r"(?im)^\s*#*\s*(Activit[eé]s|Activites)\s+pr[eé]vues.*$", 'structure_activites_prevues'),
        (r"(?im)^\s*#*\s*[ÉE]valuation\s+sommative.*$", 'eval_evaluation_sommative'),
        (r"(?im)^\s*#*\s*Nature\s+des\s+[eé]valuations?\s+sommatives?.*$", 'eval_nature_evaluations_sommatives'),
        (r"(?im)^\s*#*\s*[ÉE]valuation\s+de\s+la\s+langue.*$", 'eval_evaluation_de_la_langue'),
        (r"(?im)^\s*#*\s*[ÉE]valuations?\s+sommatives?\s+des\s+apprentissages.*$", 'eval_evaluation_sommatives_apprentissages'),
        (r"(?im)^\s*#*\s*Savoir[-\s]?être.*$", 'savoir_etre__list'),
        (r"(?im)^\s*#*\s*Objets?\s+cibles?.*$", 'objets_cibles__list'),
    ]

    matches = []
    for pat, key in patterns:
        for m in re.finditer(pat, text):
            matches.append((m.start(), m.end(), key))
    if not matches:
        return {}
    matches.sort(key=lambda t: t[0])

    out: dict = {}
    for i, (start, end, key) in enumerate(matches):
        next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        body = text[end:next_start].strip()
        if not body:
            continue
        if key.endswith('__list'):
            items = []
            for line in body.splitlines():
                li = line.strip().lstrip('-•').strip()
                if len(li) >= 3:
                    items.append(li)
            if items:
                if key == 'savoir_etre__list':
                    out['savoir_etre'] = items
                elif key == 'objets_cibles__list':
                    out.setdefault('fields_with_description', {})
                    out['fields_with_description']['Objets cibles'] = [
                        {'texte': it, 'description': ''} for it in items
                    ]
        else:
            para = body.split('\n\n', 1)[0].strip()
            if para:
                out.setdefault('fields', {})
                out['fields'][key] = para

    return out



@shared_task(bind=True, name='src.app.tasks.import_plan_cadre.import_plan_cadre_preview_task')
def import_plan_cadre_preview_task(self, plan_cadre_id: int, doc_text: str, ai_model: str, user_id: int, file_path: str | None = None):
    """
    Celery task: analyse un DOCX (texte brut) et retourne un APERÇU des modifications
    sans appliquer directement sur la base de données, pour permettre une comparaison.
    """
    try:
        # Streaming buffer to display live progress in the unified modal
        stream_buf = ""
        reasoning_summary_text = ""
        def push(step_msg: str, step: str = "", progress: int = None):
            nonlocal stream_buf
            try:
                stream_buf += (step_msg + "\n")
                meta = { 'message': step_msg, 'stream_buffer': stream_buf }
                if step: meta['step'] = step
                if progress is not None: meta['progress'] = progress
                self.update_state(state='PROGRESS', meta=meta)
            except Exception:
                pass
        push("Initialisation de l'import (aperçu)…", step='init', progress=1)
        plan = db.session.get(PlanCadre, plan_cadre_id)
        if not plan:
            return {"status": "error", "message": "Plan-cadre non trouvé."}

        user = db.session.query(User).with_for_update().get(user_id)
        if not user:
            return {"status": "error", "message": "Utilisateur introuvable."}
        if not user.openai_key:
            return {"status": "error", "message": "Clé OpenAI non configurée."}
        if user.credits is None:
            user.credits = 0.0
            db.session.commit()
        if user.credits <= 0:
            return {"status": "error", "message": "Crédits insuffisants."}

        push("Préparation du texte et du prompt…", step='prepare', progress=5)
        prompt = (
            "Texte du plan-cadre (brut):\n---\n{doc_text}\n---\n"
        ).format(doc_text=doc_text[:150000])

        push("Appel au modèle IA…", step='ai_call', progress=20)
        client = OpenAI(api_key=user.openai_key)
        pc_settings = PlanCadreImportPromptSettings.get_current()
        model_name = (ai_model or (pc_settings.ai_model if pc_settings else None) or 'gpt-5')
        # Prompt système (SectionAISettings) pour l'import
        from ..models import SectionAISettings
        try:
            sa_impt = SectionAISettings.get_for('plan_cadre_import')
            system_prompt_text = (getattr(sa_impt, 'system_prompt', None) or '').strip()
        except Exception:
            system_prompt_text = ''

        parsed = None
        if file_path:
            try:
                import os as _os
                size_info = None
                try:
                    st = _os.stat(file_path)
                    size_info = st.st_size
                except Exception:
                    size_info = None
                push(f"Fichier prêt: {file_path} ({(size_info or 0)} octets)", step='file', progress=18)

                # Convertir .docx -> .pdf si nécessaire (OpenAI ne prend pas .docx en input_file)
                upload_path = file_path
                try:
                    if file_path.lower().endswith('.docx'):
                        pdf_path = file_path[:-5] + '.pdf'
                        push("Conversion DOCX → PDF (haute fidélité)…", step='convert', progress=19)
                        # 1) Prefer Mammoth (DOCX->HTML) + WeasyPrint (HTML->PDF) for better formatting
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
                            except Exception:
                                # Fallback to plain-text PDF
                                _create_pdf_from_text(doc_text or 'Document importé', pdf_path)
                        else:
                            # Fallback to plain-text PDF
                            _create_pdf_from_text(doc_text or 'Document importé', pdf_path)
                        upload_path = pdf_path
                        try:
                            st2 = _os.stat(upload_path)
                            push(f"PDF prêt: {upload_path} ({st2.st_size} octets)", step='convert', progress=20)
                        except Exception:
                            push(f"PDF prêt: {upload_path}", step='convert', progress=20)
                except Exception:
                    pass

                with open(upload_path, 'rb') as f:
                    up = client.files.create(file=f, purpose='user_data')
                    file_id = getattr(up, 'id', None)
                push(f"Upload OpenAI réussi (file_id={file_id})" if file_id else "Upload OpenAI non disponible", step='upload', progress=22)
            except Exception:
                file_id = None
                push("Échec upload vers OpenAI; repli en mode texte brut.", step='upload', progress=19)

            # Build compact instruction (do not inline full text when using file)
            template = (pc_settings.prompt_template if pc_settings else '')
            if '{doc_text}' in (template or ''):
                compact_prompt = _format_import_prompt(template, '(document joint)')
            else:
                # Si aucun template configuré, ne pas injecter d'instructions côté user/system
                compact_prompt = template or ''

            # Define JSON schema expected
            json_schema = {
                "type": "object",
                "properties": {
                    "place_intro": {"type": ["string", "null"]},
                    "objectif_terminal": {"type": ["string", "null"]},
                    "structure_intro": {"type": ["string", "null"]},
                    "structure_activites_theoriques": {"type": ["string", "null"]},
                    "structure_activites_pratiques": {"type": ["string", "null"]},
                    "structure_activites_prevues": {"type": ["string", "null"]},
                    "eval_evaluation_sommative": {"type": ["string", "null"]},
                    "eval_nature_evaluations_sommatives": {"type": ["string", "null"]},
                    "eval_evaluation_de_la_langue": {"type": ["string", "null"]},
                    "eval_evaluation_sommatives_apprentissages": {"type": ["string", "null"]},
                    "competences_developpees": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "competences_certifiees": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "cours_corequis": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "cours_prealables": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "cours_relies": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "objets_cibles": {"type": "array", "items": {"type": "object", "properties": {"texte": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}}},
                    "savoir_etre": {"type": "array", "items": {"type": "string"}},
                    "capacites": {"type": "array", "items": {"type": "object", "properties": {
                        "capacite": {"type": ["string", "null"]},
                        "description_capacite": {"type": ["string", "null"]},
                        "ponderation_min": {"type": ["integer", "null"]},
                        "ponderation_max": {"type": ["integer", "null"]},
                        "savoirs_necessaires": {"type": "array", "items": {"type": "string"}},
                        "savoirs_faire": {"type": "array", "items": {"type": "object", "properties": {
                            "texte": {"type": ["string", "null"]},
                            "cible": {"type": ["string", "null"]},
                            "seuil_reussite": {"type": ["string", "null"]},
                        } }},
                        "moyens_evaluation": {"type": "array", "items": {"type": "string"}}
                    }}}
                },
                "additionalProperties": True
            }

            try:
                if file_id:
                    # Build request
                    # Déplacer les consignes dans le prompt système; l'utilisateur ne fournit que le fichier
                    sys_text = (system_prompt_text or '')
                    if compact_prompt:
                        sys_text = (sys_text + "\n\n" + compact_prompt).strip()
                    request_input = [
                        {"role": "system", "content": [{"type": "input_text", "text": sys_text}]},
                        {"role": "user", "content": [{"type": "input_file", "file_id": file_id}]}
                    ]
                    request_kwargs = dict(
                        model=model_name,
                        input=request_input,
                        text={
                            "format": {
                                "type": "json_schema",
                                "name": "PlanCadreImport",
                                "strict": False,
                                "schema": json_schema
                            }
                        },
                        store=True,
                        reasoning={"summary": "auto"},
                    )
                    # Streaming for live updates
                    streamed_text = ""
                    reasoning_summary_text = ''
                    final_response = None
                    try:
                        with client.responses.stream(**request_kwargs) as stream:
                            for event in stream:
                                etype = getattr(event, 'type', '') or ''
                                if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                                    delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                                    if delta:
                                        streamed_text += delta
                                        try:
                                            self.update_state(state='PROGRESS', meta={ 'stream_chunk': delta, 'stream_buffer': streamed_text })
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
                                                self.update_state(
                                                    state='PROGRESS',
                                                    meta={
                                                        'message': 'Résumé du raisonnement',
                                                        'reasoning_summary': reasoning_summary_text
                                                    }
                                                )
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                elif etype.endswith('response.completed'):
                                    pass
                                elif etype.endswith('response.error'):
                                    pass
                            final_response = stream.get_final_response()
                            if not reasoning_summary_text:
                                reasoning_summary_text = _extract_reasoning_summary_from_response(final_response)
                                if reasoning_summary_text:
                                    try:
                                        self.update_state(
                                            state='PROGRESS',
                                            meta={'message': 'Résumé du raisonnement', 'reasoning_summary': reasoning_summary_text}
                                        )
                                    except Exception:
                                        pass
                    except Exception:
                        # Fallback non-stream
                        final_response = client.responses.create(**request_kwargs)
                        reasoning_summary_text = _extract_reasoning_summary_from_response(final_response)
                        if reasoning_summary_text:
                            try:
                                self.update_state(
                                    state='PROGRESS',
                                    meta={'message': 'Résumé du raisonnement', 'reasoning_summary': reasoning_summary_text}
                                )
                            except Exception:
                                pass

                    # Parse final response
                    json_text = None
                    try:
                        parsed_json = getattr(final_response, 'output_parsed', None)
                    except Exception:
                        parsed_json = None
                    if parsed_json is not None:
                        try:
                            parsed = ImportPlanCadreResponse.model_validate(parsed_json)
                        except Exception:
                            # As dict already
                            parsed = ImportPlanCadreResponse.parse_obj(parsed_json)
                    else:
                        try:
                            json_text = getattr(final_response, 'output_text', None)
                        except Exception:
                            json_text = None
                        if not json_text and streamed_text:
                            json_text = streamed_text
                        if not json_text:
                            try:
                                for out in getattr(final_response, 'output', []) or []:
                                    for c in getattr(out, 'content', []) or []:
                                        t = getattr(c, 'text', None)
                                        if t:
                                            json_text = t
                                            break
                                    if json_text:
                                        break
                            except Exception:
                                json_text = None
                        if json_text:
                            import json as _json
                            data = _json.loads(json_text)
                            try:
                                parsed = ImportPlanCadreResponse.model_validate(data)
                            except Exception:
                                parsed = ImportPlanCadreResponse.parse_obj(data)
                    # propagate usage for crediting
                    try:
                        response = final_response
                    except Exception:
                        pass
            except Exception as e:
                push(f"Erreur analyse fichier: {getattr(e, 'message', str(e))}", step='ai_call', progress=35)
                parsed = None

        if parsed is None:
            # Fallback to text-based parsing
            template = (pc_settings.prompt_template if pc_settings else None)
            if not template or '{doc_text}' not in template:
                template = (
                    "Texte du plan-cadre (brut):\n---\n{doc_text}\n---\n"
                )
            prompt = _format_import_prompt(template, doc_text)
            response = client.responses.parse(
                model=model_name,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt_text}]},
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
                ],
                text_format=ImportPlanCadreResponse,
            )
            parsed = _extract_first_parsed(response)
            if not reasoning_summary_text:
                reasoning_summary_text = _extract_reasoning_summary_from_response(response)
                if reasoning_summary_text:
                    try:
                        self.update_state(
                            state='PROGRESS',
                            meta={'message': 'Résumé du raisonnement', 'reasoning_summary': reasoning_summary_text}
                        )
                    except Exception:
                        pass

        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model or 'gpt-5')
        user.credits = max((user.credits or 0.0) - cost, 0.0)
        db.session.commit()

        push("Réception et parsing de la réponse…", step='parse', progress=60)
        if not parsed:
            return {"status": "error", "message": "Réponse IA invalide."}

        # Fallback: enrich cible/seuil à partir du texte si manquants
        try:
            _fallback_fill_cible_seuil(doc_text, parsed)
        except Exception:
            logger.debug("Fallback cible/seuil non appliqué (preview)")

        push("Construction de l'aperçu des modifications…", step='build_preview', progress=75)
        # Construire la structure 'proposed' compatible avec la vue de revue
        fields = {}
        for key in [
            'place_intro', 'objectif_terminal', 'structure_intro',
            'structure_activites_theoriques', 'structure_activites_pratiques',
            'structure_activites_prevues', 'eval_evaluation_sommative',
            'eval_nature_evaluations_sommatives', 'eval_evaluation_de_la_langue',
            'eval_evaluation_sommatives_apprentissages'
        ]:
            val = _sanitize_str(getattr(parsed, key, None))
            if val is not None:
                fields[key] = val

        def model_list_to_dicts(items):
            out = []
            for it in (items or []):
                if it is None:
                    continue
                texte = _sanitize_str(getattr(it, 'texte', None))
                description = _sanitize_str(getattr(it, 'description', None))
                out.append({
                    'texte': texte or '',
                    'description': description or ''
                })
            return out

        fields_with_description = {}
        mapping = {
            'Description des compétences développées': parsed.competences_developpees,
            'Description des Compétences certifiées': parsed.competences_certifiees,
            'Description des cours corequis': parsed.cours_corequis,
            'Description des cours préalables': parsed.cours_prealables,
            'Description des cours reliés': parsed.cours_relies,
            'Objets cibles': parsed.objets_cibles,
        }
        for display_name, items in mapping.items():
            lst = model_list_to_dicts(items)
            if lst:
                fields_with_description[display_name] = lst

        capacites = []
        for cap in (parsed.capacites or []):
            if not cap:
                continue
            capacites.append({
                'capacite': _sanitize_str(cap.capacite) or '',
                'description_capacite': _sanitize_str(cap.description_capacite) or '',
                'ponderation_min': int(cap.ponderation_min or 0) if cap.ponderation_min is not None else 0,
                'ponderation_max': int(cap.ponderation_max or 0) if cap.ponderation_max is not None else 0,
                'savoirs_necessaires': [ (_sanitize_str(sn) or '') for sn in (cap.savoirs_necessaires or []) if (_sanitize_str(sn) or '').strip() ],
                'savoirs_faire': [
                    {
                        'texte': _sanitize_str(sf.texte) if sf else '',
                        'cible': _sanitize_str(sf.cible) if sf else '',
                        'seuil_reussite': _sanitize_str(sf.seuil_reussite) if sf else ''
                    } for sf in (cap.savoirs_faire or []) if sf
                ],
                'moyens_evaluation': [ (_sanitize_str(me) or '') for me in (cap.moyens_evaluation or []) if (_sanitize_str(me) or '').strip() ]
            })

        proposed = {}
        if fields:
            proposed['fields'] = fields
        if fields_with_description:
            proposed['fields_with_description'] = fields_with_description
        if parsed.savoir_etre:
            proposed['savoir_etre'] = [se for se in parsed.savoir_etre if (se or '').strip()]
        if capacites:
            proposed['capacites'] = capacites

        # Heuristic fallback when AI returns nothing usable
        if not proposed:
            try:
                heuristic = _heuristic_extract_basic_fields(doc_text)
                if heuristic:
                    proposed = heuristic
            except Exception:
                logger.debug("Heuristic basic extraction failed (preview)")

        # Indiquer le mode APERÇU pour déclencher l'écran de comparaison côté UI
        result = {
            'status': 'success',
            'message': 'Analyse du DOCX terminée. Aperçu des changements disponible.',
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'preview': True,
            'proposed': proposed
        }
        try:
            result['validation_url'] = f"/plan_cadre/{plan.id}/review?task_id={self.request.id}"
        except Exception:
            pass
        # Final streaming update before marking success
        try:
            stream_buf += "Pré-analyse terminée. Ouverture de la revue…\n"
            result['stream_buffer'] = stream_buf
            if reasoning_summary_text:
                result['reasoning_summary'] = reasoning_summary_text
        except Exception:
            pass
        self.update_state(state='SUCCESS', meta=result)
        return result

    except Exception as e:
        logger.exception("Erreur lors de l'aperçu d'import du plan-cadre")
        return {"status": "error", "message": str(e)}
