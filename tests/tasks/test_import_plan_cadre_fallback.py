import textwrap

from src.app.tasks.import_plan_cadre import ImportPlanCadreResponse, AICapacite, AISavoirFaire, _fallback_fill_cible_seuil


def make_sf_list(n):
    return [AISavoirFaire(texte=f"SF {i+1}") for i in range(n)]


def test_fallback_fills_cible_and_seuil_by_order():
    # Build a minimal doc_text containing a Capacité 1 block with 5 cibles then 5 seuils
    doc_text = textwrap.dedent(
        """
        Capacité 1 - Concevoir et planifier un projet de réseau et technologies de l’information 30 % - 40 %
        Rédiger un cahier des charges complet et cohérent couvrant besoins, contraintes, critères de succès et livrables.
        Concevoir une architecture claire et justifiée répondant aux exigences de performance, sécurité et maintenance.
        Produire un plan détaillé avec jalons, ressources, risques et plan de tests associés.
        Réaliser une analyse de risques exhaustive et proposer des mesures d’atténuation claires.
        Définir des plans de test détaillés avec critères de réussite mesurables.
        Rédiger un cahier des charges présentant les besoins principaux, les contraintes majeures et les livrables essentiels.
        Proposer une architecture fonctionnelle qui couvre la majorité des exigences essentielles.
        Fournir un plan sommaire avec jalons principaux et ressources estimées.
        Identifier les principaux risques et proposer des mesures d’atténuation basiques.
        Définir des tests de base et des critères d’acceptation généraux.
        Moyens d'évaluation: Évaluation du cahier des charges et des documents de conception
        Capacité 2 - Header suivant
        """
    ).strip()

    parsed = ImportPlanCadreResponse(
        capacites=[
            AICapacite(
                capacite="Capacité 1 - Concevoir et planifier un projet de réseau et technologies de l’information",
                description_capacite="",
                ponderation_min=30,
                ponderation_max=40,
                savoirs_faire=make_sf_list(5),
            )
        ]
    )

    # Ensure initially null
    assert all(sf.cible is None and sf.seuil_reussite is None for sf in parsed.capacites[0].savoirs_faire)

    _fallback_fill_cible_seuil(doc_text, parsed)

    filled = parsed.capacites[0].savoirs_faire
    assert all(sf.cible for sf in filled), "All cible should be filled"
    assert all(sf.seuil_reussite for sf in filled), "All seuil_reussite should be filled"

