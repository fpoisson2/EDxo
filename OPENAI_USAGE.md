# Synthèse des appels OpenAI dans le projet

Ce document recense tous les points du code qui appellent l’API OpenAI, le type d’API utilisé, la fonctionnalité couverte, et si ces appels sont réellement utilisés par l’application (routes ou tâches déclenchées depuis l’UI/API) au moment de l’analyse.

| Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé |
|---|---|---|---|---|---|
| src/ocr_processing/api_clients.py | find_competences_pages | Responses, Files | responses.create, files.create | OCR: détection bornes de pages des compétences (formation spécifique) | Partiel (utilisé via extraire_toutes_les_competences) |
| src/ocr_processing/api_clients.py | extraire_toutes_les_competences | Responses | responses.create | OCR: pipeline pages→texte→JSON compétences | Partiel (utilisé localement) |
| src/ocr_processing/api_clients.py | find_section_with_openai | Responses | responses.create | OCR: localisation section « Formation spécifique » | Partiel |
| src/ocr_processing/api_clients.py | extraire_competences_depuis_txt | Responses | responses.create | OCR: extraction JSON compétences à partir de texte | Oui (appelé par task OCR legacy helper) |
| src/ocr_processing/api_clients.py | extraire_competences_depuis_pdf | Responses, Files | responses.stream, responses.create, files.create | OCR: extraction directe JSON compétences depuis PDF | Oui (appelé par src/app/tasks/ocr.py) |
| src/app/routes/chat.py | SSE chat streaming | Responses | responses.create (stream/non-stream) | Chat IA (SSE, suivi de thread) | Oui |
| src/app/routes/gestion_programme.py | update_verifier_plan_cours | Chat Completions (beta) | beta.chat.completions.parse | Vérification de plan de cours en 2 passes (o3-mini → gpt-5) | Oui |
| src/app/routes/evaluation.py | generate_six_level_grid | Chat Completions (beta) | beta.chat.completions.parse | Génération grille d’évaluation à 6 niveaux | Oui |
| src/app/routes/plan_de_cours.py | import_docx_start (traitement) | Responses | responses.parse | Import DOCX → parsing structuré plan de cours | Oui |
| src/app/routes/plan_de_cours.py | generate_calendar (traitement) | Responses | responses.parse | Génération calendrier du plan de cours | Oui |
| src/app/routes/plan_de_cours.py | generate_evaluations (traitement) | Responses | responses.parse | Génération/MAJ des évaluations du plan de cours | Oui |
| src/app/routes/plan_de_cours.py | autres parse structurés | Responses | responses.parse | Autres sections plan de cours (structuré Pydantic) | Oui |
| src/app/tasks/generation_logigramme.py | generate_programme_logigramme_task | Responses | responses.stream, responses.create | Génération du logigramme cours→compétence | Oui (déclenché par /programme/<id>/logigramme/generate) |
| src/app/tasks/generation_grille.py | generate_programme_grille_task | Responses | responses.stream, responses.create | Génération de la grille de cours par session | Oui (déclenché par /programme/<id>/grille/generate) |
| src/app/tasks/import_grille.py | extract_grille_from_pdf_task | Responses, Files | files.create, responses.stream, responses.create | Import d’une grille depuis PDF (JSON schema strict) | Oui (déclenché par /grille/import) |
| src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_all_task | Responses | responses.stream, responses.parse | Génération complète du plan de cours (sections + évals) | Oui (déclenché par /plan_de_cours/generate_all_start) |
| src/app/tasks/generation_plan_de_cours.py | sous-appels (évaluations, etc.) | Responses | responses.stream, responses.parse | Génération ciblée (évaluations, etc.) | Oui |
| src/app/tasks/import_plan_de_cours.py | import_plan_de_cours_task | Responses | responses.parse | Import texte DOCX → plan de cours (structuré) | Oui (appelé par route d’import DOCX plan de cours) |
| src/app/tasks/import_plan_cadre.py | import_plan_cadre_preview_task | Responses, Files | files.create, responses.stream, responses.create, responses.parse | Import DOCX plan‑cadre (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/import_docx_start) |
| src/app/tasks/generation_plan_cadre.py | generate_plan_cadre_content_task | Responses | responses.stream, responses.create | Génération/amélioration du plan‑cadre (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/generate_content) |

Notes d’usage et portée
- “Oui” signifie que l’appel est relié à un endpoint Flask ou une tâche Celery effectivement déclenchée depuis l’UI/flux documenté.
- “Partiel” signifie utilitaire ou fonction intermédiaire appelée par d’autres helpers dans le module, mais pas directement exposée à l’UI ; encore utilisée dans des chemins secondaires.
- Tests: les fichiers de tests patchent `OpenAI` mais n’appellent pas l’API réelle (pas listés ici comme “utilisés”).

Catégorisation par API
- Responses: principal canal (création, streaming, parsing structuré avec Pydantic/JSON schema).
- Chat Completions (beta): utilisé dans deux endpoints (gestion programme, grille 6 niveaux).
- Assistants: aucun usage trouvé.
- Files: upload de PDF pour les tâches d’import/ocr.

Dernière mise à jour: générée automatiquement par inspection de code à la date de l’analyse.

