import inspect

def test_import_plan_cadre_reasoning_summary_contains_message():
    from src.app.tasks import import_plan_cadre
    source = inspect.getsource(import_plan_cadre.import_plan_cadre_preview_task)
    assert "'message': 'Résumé du raisonnement'" in source
