import logging
import re
import unicodedata
from typing import Dict, Optional

from celery import shared_task
from openai import OpenAI
from pydantic import BaseModel, Field

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    PlanDeCours, PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
    PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations, PlanDeCoursEvaluationsCapacites,
    User
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
        for item in outputs:
            contents = getattr(item, 'content', None) or []
            for c in contents:
                parsed = getattr(c, 'parsed', None)
                if parsed is not None:
                    return parsed
    except Exception:
        pass
    return None


@shared_task(bind=True, name='src.app.tasks.import_plan_de_cours.import_plan_de_cours_task')
def import_plan_de_cours_task(self, plan_de_cours_id: int, doc_text: str, ai_model: str, user_id: int):
    """Celery task: parse DOCX text via OpenAI, update PlanDeCours and return UI payload."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}

        cours = plan.cours
        plan_cadre = cours.plan_cadre if cours else None

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

        # Note: escape all literal braces in the JSON example ({{ and }})
        # so that .format only processes our named placeholders below.
        prompt = (
            "Tu es un assistant pédagogique. Analyse le plan de cours fourni (texte brut extrait d'un DOCX). "
            "Le texte peut contenir des tableaux rendus en Markdown, encadrés par ‘TABLE n:’ et ‘ENDTABLE’. "
            "TIENS ABSOLUMENT COMPTE du contenu des tableaux (ils prévalent sur le texte libre en cas de doublon). "
            "Retourne un JSON STRICTEMENT au format suivant (clés exactes, valeurs nulles si absentes):\n"
            "{{\n"
            "  'presentation_du_cours': str | null,\n"
            "  'objectif_terminal_du_cours': str | null,\n"
            "  'organisation_et_methodes': str | null,\n"
            "  'accomodement': str | null,\n"
            "  'evaluation_formative_apprentissages': str | null,\n"
            "  'evaluation_expression_francais': str | null,\n"
            "  'materiel': str | null,\n"
            "  'calendriers': [ {{ 'semaine': int | null, 'sujet': str | null, 'activites': str | null, 'travaux_hors_classe': str | null, 'evaluations': str | null }} ],\n"
            "  'nom_enseignant': str | null,\n"
            "  'telephone_enseignant': str | null,\n"
            "  'courriel_enseignant': str | null,\n"
            "  'bureau_enseignant': str | null,\n"
            "  'disponibilites': [ {{ 'jour_semaine': str | null, 'plage_horaire': str | null, 'lieu': str | null }} ],\n"
            "  'mediagraphies': [ {{ 'reference_bibliographique': str | null }} ],\n"
            "  'evaluations': [ {{ 'titre_evaluation': str | null, 'description': str | null, 'semaine': int | null, 'capacites': [ {{ 'capacite': str | null, 'ponderation': str | null }} ] }} ]\n"
            "}}\n\n"
            "Consignes spécifiques aux tableaux:\n"
            "- Les tableaux (Markdown) peuvent décrire le calendrier: colonnes typiques ‘Semaine’, ‘Sujet’, ‘Activités’, ‘Travaux hors classe’, ‘Évaluations’. Mappe chaque ligne vers un objet dans 'calendriers'.\n"
            "- Les tableaux d’évaluation peuvent indiquer des ‘Titre’, ‘Description’, ‘Semaine’, et des pondérations par ‘Capacité’.\n"
            "  Dans ce cas, crée des objets 'evaluations' et, pour chaque capacité, ajoute {{ 'capacite': libellé exact, 'ponderation': valeur }}.\n"
            "- Si une information n’est pas trouvée, mets null. Si conflit tableau/texte, privilégie le tableau.\n\n"
            "Contexte: cours {cours_code} - {cours_nom}, session {session}.\n"
            "Texte du plan de cours:\n---\n{doc_text}\n---\n"
        ).format(
            cours_code=getattr(cours, 'code', '') or '',
            cours_nom=getattr(cours, 'nom', '') or '',
            session=plan.session,
            doc_text=(doc_text or '')[:120000],
        )

        self.update_state(state='PROGRESS', meta={'message': "Analyse du .docx en cours..."})

        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=prompt,
            text_format=ImportPlanDeCoursResponse,
            reasoning={"summary": "auto"},
        )
        streamed_text = ""
        reasoning_summary_text = ""
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
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                            except Exception:
                                pass
                final_response = stream.get_final_response()
        except Exception:
            final_response = client.responses.parse(**request_kwargs)

        usage_prompt = final_response.usage.input_tokens if hasattr(final_response, 'usage') else 0
        usage_completion = final_response.usage.output_tokens if hasattr(final_response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        parsed = _extract_first_parsed(final_response)
        if parsed is None:
            return {"status": "error", "message": "Aucune donnée renvoyée par le modèle."}

        # Update fields
        plan.presentation_du_cours = parsed.presentation_du_cours or plan.presentation_du_cours
        plan.objectif_terminal_du_cours = parsed.objectif_terminal_du_cours or plan.objectif_terminal_du_cours
        plan.organisation_et_methodes = parsed.organisation_et_methodes or plan.organisation_et_methodes
        plan.accomodement = parsed.accomodement or plan.accomodement
        plan.evaluation_formative_apprentissages = parsed.evaluation_formative_apprentissages or plan.evaluation_formative_apprentissages
        plan.evaluation_expression_francais = parsed.evaluation_expression_francais or plan.evaluation_expression_francais
        plan.materiel = parsed.materiel or plan.materiel

        plan.nom_enseignant = parsed.nom_enseignant or plan.nom_enseignant
        plan.telephone_enseignant = parsed.telephone_enseignant or plan.telephone_enseignant
        plan.courriel_enseignant = parsed.courriel_enseignant or plan.courriel_enseignant
        plan.bureau_enseignant = parsed.bureau_enseignant or plan.bureau_enseignant

        # Calendriers (replace)
        for cal in plan.calendriers:
            db.session.delete(cal)
        for entry in parsed.calendriers or []:
            db.session.add(PlanDeCoursCalendrier(
                plan_de_cours_id=plan.id,
                semaine=entry.semaine,
                sujet=entry.sujet,
                activites=entry.activites,
                travaux_hors_classe=entry.travaux_hors_classe,
                evaluations=entry.evaluations,
            ))

        # Médiagraphies (replace)
        for m in plan.mediagraphies:
            db.session.delete(m)
        for itm in parsed.mediagraphies or []:
            if itm.reference_bibliographique:
                db.session.add(PlanDeCoursMediagraphie(
                    plan_de_cours_id=plan.id,
                    reference_bibliographique=itm.reference_bibliographique,
                ))

        # Disponibilités (replace)
        for d in plan.disponibilites:
            db.session.delete(d)
        for disp in parsed.disponibilites or []:
            if disp.jour_semaine or disp.plage_horaire or disp.lieu:
                db.session.add(PlanDeCoursDisponibiliteEnseignant(
                    plan_de_cours_id=plan.id,
                    jour_semaine=disp.jour_semaine,
                    plage_horaire=disp.plage_horaire,
                    lieu=disp.lieu,
                ))

        # Évaluations (replace)
        for ev in plan.evaluations:
            db.session.delete(ev)
        for ev in parsed.evaluations or []:
            if not (ev.titre_evaluation or ev.description or ev.semaine or ev.capacites):
                continue
            new_ev = PlanDeCoursEvaluations(
                plan_de_cours_id=plan.id,
                titre_evaluation=ev.titre_evaluation,
                description=ev.description,
                semaine=ev.semaine,
            )
            for cap_in in ev.capacites or []:
                cap_id = _resolve_capacity_id(cap_in.capacite, plan_cadre)
                # N'ajoute le lien que si on a une résolution valide
                if cap_id is not None:
                    new_ev.capacites.append(PlanDeCoursEvaluationsCapacites(
                        capacite_id=cap_id,
                        ponderation=cap_in.ponderation,
                    ))
            db.session.add(new_ev)

        db.session.commit()

        # Build payload for UI
        payload = {
            'fields': {
                'presentation_du_cours': plan.presentation_du_cours,
                'objectif_terminal_du_cours': plan.objectif_terminal_du_cours,
                'organisation_et_methodes': plan.organisation_et_methodes,
                'accomodement': plan.accomodement,
                'evaluation_formative_apprentissages': plan.evaluation_formative_apprentissages,
                'evaluation_expression_francais': plan.evaluation_expression_francais,
                'materiel': plan.materiel,
                'nom_enseignant': plan.nom_enseignant,
                'telephone_enseignant': plan.telephone_enseignant,
                'courriel_enseignant': plan.courriel_enseignant,
                'bureau_enseignant': plan.bureau_enseignant,
            },
            'calendriers': [
                {
                    'semaine': c.semaine,
                    'sujet': c.sujet,
                    'activites': c.activites,
                    'travaux_hors_classe': c.travaux_hors_classe,
                    'evaluations': c.evaluations,
                } for c in plan.calendriers
            ],
            'mediagraphies': [
                {'reference_bibliographique': m.reference_bibliographique} for m in plan.mediagraphies
            ],
            'disponibilites': [
                {
                    'jour_semaine': d.jour_semaine,
                    'plage_horaire': d.plage_horaire,
                    'lieu': d.lieu,
                } for d in plan.disponibilites
            ],
            'evaluations': [
                {
                    'titre_evaluation': e.titre_evaluation,
                    'description': e.description,
                    'semaine': e.semaine,
                    'capacites': [
                        {
                            'capacite_id': c.capacite_id,
                            'capacite_nom': (c.capacite.capacite if c.capacite else None),
                            'ponderation': c.ponderation,
                        } for c in e.capacites
                    ]
                } for e in plan.evaluations
            ],
            # Identifiants utiles pour la notification + lien direct
            'cours_id': plan.cours_id,
            'plan_id': plan.id,
            'session': plan.session,
            # Lien de validation/comparaison standardisé
            'validation_url': f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            # Lien direct possible vers l'affichage du plan de cours (fallback)
            'plan_de_cours_url': f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            'reasoning_summary': reasoning_summary_text,
        }

        return {"status": "success", **payload}

    except Exception as e:
        logger.exception("Erreur dans la tâche import_plan_de_cours_task")
        return {"status": "error", "message": str(e)}
