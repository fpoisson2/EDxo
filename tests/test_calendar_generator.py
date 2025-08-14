from types import SimpleNamespace

from src.utils.calendar_generator import build_calendar_prompt


def _simple(text: str):
    return SimpleNamespace(texte=text)


def test_build_calendar_prompt_includes_plan_cadre_sections():
    plan_cadre = SimpleNamespace(
        cours=SimpleNamespace(code="MATH101", nom="Mathématiques"),
        place_intro="Position du cours",
        objectif_terminal="Objectif X",
        structure_intro="Structure Y",
        structure_activites_theoriques="Théorie",
        structure_activites_pratiques="Pratique",
        structure_activites_prevues="Prévu",
        eval_evaluation_sommative="Exam final",
        eval_nature_evaluations_sommatives="Tests",
        eval_evaluation_de_la_langue="Éval langue",
        eval_evaluation_sommatives_apprentissages="Synthèse",
        additional_info="Notes diverses",
        capacites=[
            SimpleNamespace(
                capacite="Cap1",
                description_capacite="Desc",
                ponderation_min=10,
                ponderation_max=30,
                savoirs_necessaires=[_simple("SN1")],
                savoirs_faire=[_simple("SF1")],
                moyens_evaluation=[_simple("ME1")],
            )
        ],
    )

    prompt = build_calendar_prompt(plan_cadre, "A25")

    assert "Capacité: Cap1" in prompt
    assert "Objectif terminal: Objectif X" in prompt
    assert "Évaluation sommative: Exam final" in prompt
    assert "SN1" in prompt
