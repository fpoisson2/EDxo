from src.app.tasks.import_plan_cadre import ImportPlanCadreResponse


def test_import_plan_cadre_aliases_map_cible_and_seuil_reussite():
    data = {
        "capacites": [
            {
                "capacite": "Capacité 1",
                "savoirs_faire": [
                    {"texte": "SF1", "cible": "C1", "seuil_reussite": "S1"},
                    {"texte": "SF2", "seuil_performance": "C2", "critere_reussite": "S2"},
                ],
            }
        ]
    }
    model = ImportPlanCadreResponse.model_validate(data)
    assert model.capacites and len(model.capacites[0].savoirs_faire) == 2
    sf1, sf2 = model.capacites[0].savoirs_faire
    # Aliased keys should populate the canonical fields
    assert sf1.seuil_performance == "C1"
    assert sf1.critere_reussite == "S1"
    assert sf2.seuil_performance == "C2"
    assert sf2.critere_reussite == "S2"

