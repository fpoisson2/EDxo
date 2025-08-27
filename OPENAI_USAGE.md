# Synthèse des appels OpenAI dans le projet

Ce document recense tous les points du code qui appellent l’API OpenAI, le type d’API utilisé, la fonctionnalité couverte, et si ces appels sont réellement utilisés par l’application (routes ou tâches déclenchées depuis l’UI/API) au moment de l’analyse.

## Plan de cours

### Génération et amélioration

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Génération globale | src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_all_task | Responses | responses.stream, responses.parse | Génération complète du plan de cours (sections + évaluations) | Oui (déclenché par /plan_de_cours/generate_all_start) | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |
| Champ ciblé | src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_field_task | Responses | responses.stream, responses.parse | Génération ciblée d’un champ | Oui | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |
| Calendrier | src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_calendar_task | Responses | responses.stream, responses.parse | Génération du calendrier | Oui | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |
| Évaluations | src/app/tasks/generation_plan_de_cours.py | generate_plan_de_cours_evaluations_task | Responses | responses.stream, responses.parse | Génération des évaluations | Oui | Paramètres IA > Plans de cours (/settings/plan-de-cours/prompts) |

### Routes (traitements intégrés)

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Calendrier | src/app/routes/plan_de_cours.py | generate_calendar (traitement) | Responses | responses.parse | Génération calendrier (intégrée) | Oui | Non |
| Évaluations | src/app/routes/plan_de_cours.py | generate_evaluations (traitement) | Responses | responses.parse | Génération/MAJ évaluations (intégrée) | Oui | Non |
| Sections | src/app/routes/plan_de_cours.py | autres parse structurés | Responses | responses.parse | Parsing structuré des sections | Oui | Non |

### Import

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Import Plan de cours | src/app/routes/plan_de_cours.py | import_docx_start (traitement) | Responses | responses.parse | Import DOCX → structuré | Oui | Non |
| Import Plan de cours | src/app/tasks/import_plan_de_cours.py | import_plan_de_cours_task | Responses | responses.parse | Import DOCX → structuré | Oui (appelé par la route) | Non |

### Vérification

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Vérification Plan de cours | src/app/routes/gestion_programme.py | update_verifier_plan_cours | Chat Completions (beta) | beta.chat.completions.parse | Vérification en 2 passes | Oui | Paramètres IA > Analyse des plans de cours (/settings/analyse_prompt) |

## Plan‑cadre

### Génération et amélioration

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Génération/Amélioration | src/app/tasks/generation_plan_cadre.py | generate_plan_cadre_content_task | Responses | responses.stream, responses.create | Génération/amélioration (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/generate_content) | Globale (Génération IA) (/settings/generation) |

### Import

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Import Plan‑cadre | src/app/tasks/import_plan_cadre.py | import_plan_cadre_preview_task | Responses, Files | files.create, responses.stream, responses.create, responses.parse | Import DOCX (aperçu/validation) | Oui (déclenché par /plan_cadre/<id>/import_docx_start) | Non |

## Logigramme

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Logigramme | src/app/tasks/generation_logigramme.py | generate_programme_logigramme_task | Responses | responses.stream, responses.create | Génération logigramme cours→compétence | Oui (déclenché par /programme/<id>/logigramme/generate) | Globale (Génération IA) (/settings/generation) |

## Grille de cours

### Génération

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Grille programme | src/app/tasks/generation_grille.py | generate_programme_grille_task | Responses | responses.stream, responses.create | Génération de la grille par session | Oui (déclenché par /programme/<id>/grille/generate) | Globale (Génération IA) (/settings/generation) |

### Import

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Import Grille | src/app/tasks/import_grille.py | extract_grille_from_pdf_task | Responses, Files | files.create, responses.stream, responses.create | Import PDF → grille (JSON) | Oui (déclenché par /grille/import) | Non |

## Compétences ministériels

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| OCR Compétences | src/ocr_processing/api_clients.py | extraire_competences_depuis_pdf | Responses, Files | responses.stream, responses.create, files.create | OCR: extraire compétences depuis PDF | Oui (appelé par src/app/tasks/ocr.py) | Paramètres IA > Devis ministériels (OCR) (/settings/ocr_prompts) |

## Chat

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Chat SSE | src/app/routes/chat.py | SSE chat streaming | Responses | responses.create (stream/non-stream) | Chat IA (SSE, suivi de thread) | Oui | Globale (Chat IA) (/settings/chat_models) |

## Grille d’évaluation

| Nom | Chemin | Endpoint / Tâche / Fonction | API OpenAI | Méthodes | Fonctionnalité | Utilisé | Prompt système |
|---|---|---|---|---|---|---|---|
| Grille d’évaluation | src/app/routes/evaluation.py | generate_six_level_grid | Chat Completions (beta) | beta.chat.completions.parse | Grille d’évaluation à 6 niveaux | Oui | Paramètres IA > Grille d’évaluation (/settings/prompt-settings) |

- Assistants: aucun usage trouvé.
- Files: upload de PDF pour les tâches d’import/OCR.

Dernière mise à jour: générée automatiquement par inspection de code à la date de l’analyse.

---

Plan d’action – Pages de paramètres IA par section

1) Modèle et formulaire
- Créer `SectionAISettings` (section unique) avec: `system_prompt`, `ai_model`, `reasoning_effort`, `verbosity`, `updated_at`.
- Ajouter `SectionAISettingsForm` (textarea + selects) alimenté par la table `openai_models` pour les choix de modèles.

2) Routes par section (pas de page globale)
- `GET/POST /settings/plan-de-cours/ai`
- `GET/POST /settings/plan-cadre/ai`
- `GET/POST /settings/logigramme/ai`
- `GET/POST /settings/grille/ai`
- `GET/POST /settings/ocr/ai`
- `GET/POST /settings/chat/ai`
- `GET/POST /settings/evaluation/ai`

3) Template commun
- Créer `settings/section_ai_settings.html` (titre/description passés en contexte) réutilisé par chaque route.

4) Persistance et robustesse
- Méthode `SectionAISettings.get_for(section)` avec création de table à la volée si absente (`checkfirst=True`).
- CSRF + validations; flash messages de succès/erreur.

5) Navigation et liens
- Ajouter des entrées vers chaque page dans le menu Paramètres existant; conserver les anciennes pages pour compatibilité.

6) Intégration (suivi)
- Brancher progressivement les tâches IA pour lire ces réglages (modèle/raisonnement/verbosité/prompt).
- Déprécier les usages « globaux » une fois migrés.
