# Guide pour les contributions des agents (EDxo)

Ce référentiel utilise des agents/outils pour automatiser des modifications de code. Pour garantir la qualité et éviter les régressions, respectez les règles suivantes à chaque demande de correctif ou de nouvelle fonctionnalité.

## Règle essentielle
- Toujours écrire des tests pertinents (pytest) pour couvrir le correctif ou la fonctionnalité ajoutée.
- Toujours exécuter la suite de tests localement avec `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q` pour accélérer l'exécution et s'assurer qu'elle passe avant de conclure la tâche.

## Détails pratiques
- Emplacement des tests: placez-les sous `tests/` avec le préfixe `test_*.py`.
- Fixtures disponibles: `tests/conftest.py` expose `app` et `client` (Flask, SQLite en mémoire, CSRF désactivé, rate‑limit en mémoire).
- Les tests n’exigent ni Redis ni clé OpenAI: la `TestConfig` interne isole les dépendances externes.
- Si un bug est reproduit par un test, commencez par écrire le test qui échoue, puis corrigez le code jusqu'à ce que le test passe.
- Ne modifiez pas de parties non liées; concentrez-vous sur la portée de la demande.
- Si des avertissements perturbent la lisibilité, nettoyez-les ou filtrez-les de manière ciblée, sans masquer des problèmes réels.

## Commandes utiles
- Lancer toute la suite (résumé concis): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
- Interrompre au premier échec pour un diagnostic rapide: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --maxfail=1`
- Exécuter un seul fichier: `pytest -q tests/test_mon_module.py`
- Exécuter un seul test: `pytest -q tests/test_mon_module.py::test_cas_specifique`
- Compter les tests rapidement (collect only): `pytest -q --collect-only | awk -F': ' '{s+=$2} END{print s}'`

## Sortie attendue
- À la fin de la tâche, indiquez brièvement:
  - Les fichiers modifiés/ajoutés.
  - Les tests ajoutés/ajustés.
  - Le résultat de `pytest -q` (nombre de tests passés, durée, et absence de warnings si demandé).

Notes spécifiques à EDxo

- Les tâches Celery exposent un suivi unifié (`/tasks/status|events|cancel|track`). Les tests couvrent déjà ces routes; n’ajoutez des mocks qu’au besoin.
- Le hub ASGI (Starlette) sert le SSE; si vous touchez à l’ASGI, gardez la compatibilité des routes existantes.

Merci de maintenir une base de code fiable et testée.
