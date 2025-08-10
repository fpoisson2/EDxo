from src.app.routes.chat import tools


def test_tool_definition():
    func = tools.get_plan_de_cours_function()
    assert func['name'] == 'get_plan_de_cours'


def test_tool_handler():
    result = tools.handle_get_plan_de_cours({'code': 'XYZ'})
    assert result == {'code': 'XYZ'}
