# Guide pour les contributions des agents (EDxo)

Ce référentiel utilise des agents/outils pour automatiser des modifications de code. Pour garantir la qualité et éviter les régressions, respectez les règles suivantes à chaque demande de correctif ou de nouvelle fonctionnalité.

## Règle essentielle
- Toujours écrire des tests pertinents (pytest) pour couvrir le correctif ou la fonctionnalité ajoutée.
- Toujours exécuter la suite de tests localement avec `pytest -q` et s'assurer qu'elle passe avant de conclure la tâche.

## Détails pratiques
- Emplacement des tests: placez-les sous `tests/` avec le préfixe `test_*.py`.
- Fixtures disponibles: utilisez celles de `tests/conftest.py` (`app`, `client`).
- Si un bug est reproduit par un test, commencez par écrire le test qui échoue, puis corrigez le code jusqu'à ce que le test passe.
- Ne modifiez pas de parties non liées; concentrez-vous sur la portée de la demande.
- Si des avertissements perturbent la lisibilité, nettoyez-les ou filtrez-les de manière ciblée, sans masquer des problèmes réels.

## Commandes utiles
- Lancer les tests: `pytest -q`
- Exécuter un seul fichier: `pytest -q tests/test_mon_module.py`
- Exécuter un seul test: `pytest -q tests/test_mon_module.py::test_cas_specifique`

## Sortie attendue
- À la fin de la tâche, indiquez brièvement:
  - Les fichiers modifiés/ajoutés.
  - Les tests ajoutés/ajustés.
  - Le résultat de `pytest -q` (nombre de tests passés, durée, et absence de warnings si demandé).

Merci de maintenir une base de code fiable et testée.
