# Inventaire des appels OpenAI (EDxo)

Ce document recense les intégrations OpenAI côté serveur, avec le pattern unifié (Responses API, Celery, SSE), les modèles utilisés, et la source des prompts.

## Analyse Plan de cours

- Chemin (start): `POST /gestion_programme/analyse_plan_de_cours/<plan_id>/start`
- Tâche Celery: `src/app/tasks/analyse_plan_de_cours.py:analyse_plan_de_cours_task`
- API: `client.responses.create` / `client.responses.stream`
- Modèle: `SectionAISettings('analyse_plan_cours').ai_model` (fallback `gpt-5`)
- Reasoning: `reasoning={ summary:'auto', effort: <sa.reasoning_effort> }`
- Sortie: `text.format = { type: 'json_schema', name: 'PlanDeCoursAIResponse', strict: true, schema: generated }`
- Prompt système: `SectionAISettings('analyse_plan_cours').system_prompt` + `AnalysePlanCoursPrompt.prompt_template`
- Données utilisateur (`message user`): JSON structuré `{ plan_cours_id, plan_cours, plan_cadre_id, plan_cadre, schema_json }`
- Streaming UI: publie `meta.stream_chunk`, `meta.stream_buffer`, `meta.reasoning_summary`
- Écriture BD: met à jour `PlanDeCours.compatibility_percentage`, `recommendation_ameliore`, `recommendation_plan_cadre`
- Credits: `calculate_call_cost(usage.input_tokens, usage.output_tokens, model)` puis décrément `User.credits`
- Payload final: `{ status, compatibility_percentage, recommendation_*, usage, validation_url }`

Note: L’ancien endpoint synchrone `POST /gestion_programme/update_verifier_plan_cours/<plan_id>` est déprécié et renvoie 410. Utiliser l’endpoint asynchrone ci‑dessus.

## Autres intégrations (existant)

- Génération Plan‑cadre: `src/app/tasks/generation_plan_cadre.py` (plusieurs sous‑tâches)
- Plan de cours (global, calendrier, évaluations): `src/app/tasks/generation_plan_de_cours.py`
- Grille d’évaluation: `src/app/tasks/generation_grille.py`
- Logigramme de compétences: `src/app/tasks/generation_logigramme.py`
- OCR/Imports: `src/app/tasks/ocr.py`, `src/app/tasks/import_plan_de_cours.py`, `src/app/tasks/import_grille.py`, `src/app/tasks/import_plan_cadre.py`
- Conversion DOCX→Schéma JSON: `src/app/tasks/docx_to_schema.py` (start `POST /docx_to_schema/start`)

Tous suivent le pattern:

- Start: endpoint POST minimal qui lance `task.delay(...)` et renvoie `202 { task_id }`
- Suivi: `/tasks/status/<task_id>` + `/tasks/events/<task_id>` + `/tasks/track/<task_id>`
- Responses API: JSON Schema strict pour des sorties typées (Pydantic), support streaming
- Crédits: facturation des tokens via `utils/openai_pricing.py`

