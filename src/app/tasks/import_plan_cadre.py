import logging
import re
import unicodedata
from typing import List, Optional, Tuple

from celery import shared_task
from openai import OpenAI
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


@shared_task(bind=True, name='src.app.tasks.import_plan_cadre.import_plan_cadre_task')
def import_plan_cadre_task(self, plan_cadre_id: int, doc_text: str, ai_model: str, user_id: int):
    """Celery task: analyse un DOCX (texte brut) et met à jour le PlanCadre."""
    try:
        plan = PlanCadre.query.get(plan_cadre_id)
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

        # Prompt d'analyse du plan-cadre
        prompt = (
            "Tu es un assistant pédagogique. Analyse le plan-cadre fourni (texte brut extrait d'un DOCX) "
            "et retourne un JSON STRICTEMENT au format suivant (clés exactes, valeurs nulles si absentes). "
            "Si le document contient un tableau/section des paramètres de l’évaluation avec des colonnes/sections 'Cible' et 'Seuil', "
            "associe chaque entrée aux 'savoirs_faire' correspondants de la même capacité (même ordre, 1:1) et renseigne 'cible' et 'seuil_reussite' (ne pas laisser null si l’information est présente).\n"
            "{{\n"
            "  'place_intro': str | null,\n"
            "  'objectif_terminal': str | null,\n"
            "  'structure_intro': str | null,\n"
            "  'structure_activites_theoriques': str | null,\n"
            "  'structure_activites_pratiques': str | null,\n"
            "  'structure_activites_prevues': str | null,\n"
            "  'eval_evaluation_sommative': str | null,\n"
            "  'eval_nature_evaluations_sommatives': str | null,\n"
            "  'eval_evaluation_de_la_langue': str | null,\n"
            "  'eval_evaluation_sommatives_apprentissages': str | null,\n"
            "  'competences_developpees': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'competences_certifiees': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_corequis': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_prealables': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_relies': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'objets_cibles': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'savoir_etre': [ str ],\n"
            "  'capacites': [ {{\n"
            "      'capacite': str | null,\n"
            "      'description_capacite': str | null,\n"
            "      'ponderation_min': int | null,\n"
            "      'ponderation_max': int | null,\n"
            "      'savoirs_necessaires': [ str ],\n"
            "      'savoirs_faire': [ {{ 'texte': str | null, 'cible': str | null, 'seuil_reussite': str | null }} ],\n"
            "      'moyens_evaluation': [ str ]\n"
            "  }} ]\n"
            "}}\n\n"
            "Renvoie uniquement le JSON, sans texte avant ni après.\n"
            "Texte du plan-cadre:\n---\n{doc_text}\n---\n"
        ).format(doc_text=doc_text[:150000])

        client = OpenAI(api_key=user.openai_key)
        response = client.responses.parse(
            model=ai_model or 'gpt-5',
            input=prompt,
            text_format=ImportPlanCadreResponse,
        )

        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model or 'gpt-5')
        user.credits = max((user.credits or 0.0) - cost, 0.0)
        db.session.commit()

        parsed = _extract_first_parsed(response)
        if not parsed:
            return {"status": "error", "message": "Réponse IA invalide."}

        # Fallback: enrich cible/seuil à partir du texte si manquants
        try:
            _fallback_fill_cible_seuil(doc_text, parsed)
        except Exception:
            logger.debug("Fallback cible/seuil non appliqué")

        # Mettre à jour les champs simples
        plan.place_intro = parsed.place_intro or plan.place_intro
        plan.objectif_terminal = parsed.objectif_terminal or plan.objectif_terminal
        plan.structure_intro = parsed.structure_intro or plan.structure_intro
        plan.structure_activites_theoriques = parsed.structure_activites_theoriques or plan.structure_activites_theoriques
        plan.structure_activites_pratiques = parsed.structure_activites_pratiques or plan.structure_activites_pratiques
        plan.structure_activites_prevues = parsed.structure_activites_prevues or plan.structure_activites_prevues
        plan.eval_evaluation_sommative = parsed.eval_evaluation_sommative or plan.eval_evaluation_sommative
        plan.eval_nature_evaluations_sommatives = parsed.eval_nature_evaluations_sommatives or plan.eval_nature_evaluations_sommatives
        plan.eval_evaluation_de_la_langue = parsed.eval_evaluation_de_la_langue or plan.eval_evaluation_de_la_langue
        plan.eval_evaluation_sommatives_apprentissages = parsed.eval_evaluation_sommatives_apprentissages or plan.eval_evaluation_sommatives_apprentissages

        # Listes avec description (remplacement)
        def replace_list(current_rel, items, model_cls):
            current_rel.clear()
            for it in (items or []):
                if not it:
                    continue
                texte = getattr(it, 'texte', None) or ''
                desc = getattr(it, 'description', None) or ''
                current_rel.append(model_cls(texte=texte, description=desc))

        replace_list(plan.competences_developpees, parsed.competences_developpees, PlanCadreCompetencesDeveloppees)
        replace_list(plan.competences_certifiees, parsed.competences_certifiees, PlanCadreCompetencesCertifiees)
        replace_list(plan.cours_corequis, parsed.cours_corequis, PlanCadreCoursCorequis)
        replace_list(plan.cours_prealables, parsed.cours_prealables, PlanCadreCoursPrealables)
        replace_list(plan.cours_relies, parsed.cours_relies, PlanCadreCoursRelies)
        replace_list(plan.objets_cibles, parsed.objets_cibles, PlanCadreObjetsCibles)

        # Savoir-être (remplacement)
        plan.savoirs_etre.clear()
        for se in (parsed.savoir_etre or []):
            if (se or '').strip():
                plan.savoirs_etre.append(PlanCadreSavoirEtre(texte=se.strip()))

        # Capacités (remplacement)
        plan.capacites.clear()
        for cap in (parsed.capacites or []):
            if not cap:
                continue
            new_cap = PlanCadreCapacites(
                capacite=(cap.capacite or ''),
                description_capacite=(cap.description_capacite or ''),
                ponderation_min=int(cap.ponderation_min or 0),
                ponderation_max=int(cap.ponderation_max or 0),
            )
            # Savoirs nécessaires
            for sn in (cap.savoirs_necessaires or []):
                if (sn or '').strip():
                    new_cap.savoirs_necessaires.append(
                        PlanCadreCapaciteSavoirsNecessaires(texte=sn.strip())
                    )
            # Savoirs faire
            for sf in (cap.savoirs_faire or []):
                if not sf:
                    continue
                new_cap.savoirs_faire.append(
                    PlanCadreCapaciteSavoirsFaire(
                        texte=(sf.texte or ''),
                        cible=(sf.cible or ''),
                        seuil_reussite=(sf.seuil_reussite or ''),
                    )
                )
            # Moyens d'évaluation
            for me in (cap.moyens_evaluation or []):
                if (me or '').strip():
                    new_cap.moyens_evaluation.append(
                        PlanCadreCapaciteMoyensEvaluation(texte=me.strip())
                    )
            plan.capacites.append(new_cap)

        db.session.commit()

        # Retour simple pour le front; on peut juste recharger la page
        return {
            'status': 'success',
            'message': 'Import du plan-cadre terminé',
            'plan_id': plan.id,
        }

    except Exception as e:
        logger.exception('Erreur lors de l\'import du plan-cadre')
        db.session.rollback()
        return {"status": "error", "message": str(e)}


@shared_task(bind=True, name='src.app.tasks.import_plan_cadre.import_plan_cadre_preview_task')
def import_plan_cadre_preview_task(self, plan_cadre_id: int, doc_text: str, ai_model: str, user_id: int):
    """
    Celery task: analyse un DOCX (texte brut) et retourne un APERÇU des modifications
    sans appliquer directement sur la base de données, pour permettre une comparaison.
    """
    try:
        plan = PlanCadre.query.get(plan_cadre_id)
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

        prompt = (
            "Tu es un assistant pédagogique. Analyse le plan-cadre fourni (texte brut extrait d'un DOCX) "
            "et retourne un JSON STRICTEMENT au format suivant (clés exactes, valeurs nulles si absentes). "
            "Si le document contient un tableau/section des paramètres de l’évaluation avec des colonnes/sections 'Cible' et 'Seuil', "
            "associe chaque entrée aux 'savoirs_faire' correspondants de la même capacité (même ordre, 1:1) et renseigne 'cible' et 'seuil_reussite' (ne pas laisser null si l’information est présente).\n"
            "{{\n"
            "  'place_intro': str | null,\n"
            "  'objectif_terminal': str | null,\n"
            "  'structure_intro': str | null,\n"
            "  'structure_activites_theoriques': str | null,\n"
            "  'structure_activites_pratiques': str | null,\n"
            "  'structure_activites_prevues': str | null,\n"
            "  'eval_evaluation_sommative': str | null,\n"
            "  'eval_nature_evaluations_sommatives': str | null,\n"
            "  'eval_evaluation_de_la_langue': str | null,\n"
            "  'eval_evaluation_sommatives_apprentissages': str | null,\n"
            "  'competences_developpees': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'competences_certifiees': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_corequis': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_prealables': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'cours_relies': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'objets_cibles': [ {{ 'texte': str | null, 'description': str | null }} ],\n"
            "  'savoir_etre': [ str ],\n"
            "  'capacites': [ {{\n"
            "      'capacite': str | null,\n"
            "      'description_capacite': str | null,\n"
            "      'ponderation_min': int | null,\n"
            "      'ponderation_max': int | null,\n"
            "      'savoirs_necessaires': [ str ],\n"
            "      'savoirs_faire': [ {{ 'texte': str | null, 'cible': str | null, 'seuil_reussite': str | null }} ],\n"
            "      'moyens_evaluation': [ str ]\n"
            "  }} ]\n"
            "}}\n\n"
            "Renvoie uniquement le JSON, sans texte avant ni après.\n"
            "Texte du plan-cadre:\n---\n{doc_text}\n---\n"
        ).format(doc_text=doc_text[:150000])

        client = OpenAI(api_key=user.openai_key)
        response = client.responses.parse(
            model=ai_model or 'gpt-5',
            input=prompt,
            text_format=ImportPlanCadreResponse,
        )

        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model or 'gpt-5')
        user.credits = max((user.credits or 0.0) - cost, 0.0)
        db.session.commit()

        parsed = _extract_first_parsed(response)
        if not parsed:
            return {"status": "error", "message": "Réponse IA invalide."}

        # Fallback: enrich cible/seuil à partir du texte si manquants
        try:
            _fallback_fill_cible_seuil(doc_text, parsed)
        except Exception:
            logger.debug("Fallback cible/seuil non appliqué (preview)")

        # Construire la structure 'proposed' compatible avec la vue de revue
        fields = {}
        for key in [
            'place_intro', 'objectif_terminal', 'structure_intro',
            'structure_activites_theoriques', 'structure_activites_pratiques',
            'structure_activites_prevues', 'eval_evaluation_sommative',
            'eval_nature_evaluations_sommatives', 'eval_evaluation_de_la_langue',
            'eval_evaluation_sommatives_apprentissages'
        ]:
            val = getattr(parsed, key, None)
            if val is not None:
                fields[key] = val

        def model_list_to_dicts(items):
            out = []
            for it in (items or []):
                if it is None:
                    continue
                texte = getattr(it, 'texte', None)
                description = getattr(it, 'description', None)
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
                'capacite': cap.capacite or '',
                'description_capacite': cap.description_capacite or '',
                'ponderation_min': int(cap.ponderation_min or 0) if cap.ponderation_min is not None else 0,
                'ponderation_max': int(cap.ponderation_max or 0) if cap.ponderation_max is not None else 0,
                'savoirs_necessaires': [ (sn or '') for sn in (cap.savoirs_necessaires or []) if (sn or '').strip() ],
                'savoirs_faire': [
                    {
                        'texte': (sf.texte or '') if sf else '',
                        'cible': (sf.cible or '') if sf else '',
                        'seuil_reussite': (sf.seuil_reussite or '') if sf else ''
                    } for sf in (cap.savoirs_faire or []) if sf
                ],
                'moyens_evaluation': [ (me or '') for me in (cap.moyens_evaluation or []) if (me or '').strip() ]
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

        # Indiquer le mode APERÇU pour déclencher l'écran de comparaison côté UI
        result = {
            'status': 'success',
            'message': 'Analyse du DOCX terminée. Aperçu des changements disponible.',
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'preview': True,
            'proposed': proposed
        }
        self.update_state(state='SUCCESS', meta=result)
        return result

    except Exception as e:
        logger.exception("Erreur lors de l'aperçu d'import du plan-cadre")
        return {"status": "error", "message": str(e)}
