# Synthèse des appels OpenAI dans le projet

Ce document recense tous les points du code qui appellent l’API OpenAI, le type d’API utilisé, la fonctionnalité couverte, et si ces appels sont réellement utilisés par l’application (routes ou tâches déclenchées depuis l’UI/API) au moment de l’analyse.

| Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|
| src/ocr_processing/api_clients.py | extraire_competences_depuis_pdf | Responses, Files | responses.stream, responses.create, files.create | OCR: extraction directe JSON compétences depuis PDF | Oui (appelé par src/app/tasks/ocr.py) | Paramètres IA > Devis ministériels (OCR) (/settings/ocr_prompts) |
| src/app/routes/chat.py | SSE chat streaming | Responses | responses.create (stream/non-stream) | Chat IA (SSE, suivi de thread) | Oui | Globale (Chat IA) (/settings/chat_models) |
| src/app/routes/gestion_programme.py | update_verifier_plan_cours | Chat Completions (beta) | beta.chat.completions.parse | Vérification de plan de cours en 2 passes (o3-mini → gpt-5) | Oui | Paramètres IA > Analyse des plans de cours (/settings/analyse_prompt) |
| src/app/routes/evaluation.py | generate_six_level_grid | Chat Completions (beta) | beta.chat.completions.parse | Génération grille d’évaluation à 6 niveaux | Oui | Paramètres IA > Grille d’évaluation (/settings/prompt-settings) |
| src/app/routes/plan_de_cours.py | import_docx_start (traitement) | Responses | responses.parse | Import DOCX → parsing structuré plan de cours | Oui | Non |
| src/app/routes/plan_de_cours.py | generate_calendar (traitement) | Responses | responses.parse | Génération calendrier du plan de cours | Oui | Non |
| src/app/routes/plan_de_cours.py | generate_evaluations (traitement) | Responses | responses.parse | Génération/MAJ des évaluations du plan de cours | Oui | Non |
| src/app/routes/plan_de_cours.py | autres parse structurés | Responses | responses.parse | Autres sections plan de cours (structuré Pydantic) | Oui | Non |
| src/app/tasks/generation_logigramme.py | generate_programme_logigramme_task | Responses | responses.stream, responses.create | Génération du logigramme cours→compétence | Oui (déclenché par /programme/<id>/logigramme/generate) | Globale (Génération IA) (/settings/generation) |
| src/app/tasks/generation_grille.py | generate_programme_grille_task | Responses | responses.stream, responses.create | Génération de la grille de cours par session | Oui (déclenché par /programme/<id>/grille/generate) | Globale (Génération IA) (/settings/generation) |
| src/app/tasks/import_grille.py | extract_grille_from_pdf_task | Responses, Files | files.create, responses.stream, responses.create | Import d’une grille depuis PDF (JSON schema strict) | Oui (déclenché par /grille/import) | Non |
| src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_all_task | Responses | responses.stream, responses.parse | Génération complète du plan de cours (sections + évals) | Oui (déclenché par /plan_de_cours/generate_all_start) | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |
| src/app/tasks/generation_plan_de_cours.py | sous-appels (évaluations, etc.) | Responses | responses.stream, responses.parse | Génération ciblée (évaluations, etc.) | Oui | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |
| src/app/tasks/import_plan_de_cours.py | import_plan_de_cours_task | Responses | responses.parse | Import texte DOCX → plan de cours (structuré) | Oui (appelé par route d’import DOCX plan de cours) | Non |
| src/app/tasks/import_plan_cadre.py | import_plan_cadre_preview_task | Responses, Files | files.create, responses.stream, responses.create, responses.parse | Import DOCX plan‑cadre (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/import_docx_start) | Non |
| src/app/tasks/generation_plan_cadre.py | generate_plan_cadre_content_task | Responses | responses.stream, responses.create | Génération/amélioration du plan‑cadre (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/generate_content) | Globale (Génération IA) (/settings/generation) |
- Assistants: aucun usage trouvé.
- Files: upload de PDF pour les tâches d’import/ocr.

Dernière mise à jour: générée automatiquement par inspection de code à la date de l’analyse.
