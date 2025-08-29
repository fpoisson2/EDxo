import asyncio

def test_mcp_search_tool_never_raises(app):
    # Import here to ensure app is created before module side-effects if any
    from src.mcp_server.server import _search_tool

    async def run():
        # Should return a dict with 'results' even for empty DB
        out = await _search_tool("tous les programmes")
        assert isinstance(out, dict)
        assert "results" in out
        assert isinstance(out["results"], list)

    with app.app_context():
        asyncio.run(run())


def test_mcp_fetch_tool_handles_bad_id(app):
    from src.mcp_server.server import _fetch_tool

    async def run():
        # Bad format should be captured and returned as an error object
        out = await _fetch_tool("not-a-valid-id")
        assert isinstance(out, dict)
        assert "error" in out

    with app.app_context():
        asyncio.run(run())


def test_mcp_fetch_tool_handles_missing_entity(app):
    from src.mcp_server.server import _fetch_tool

    async def run():
        # Valid prefix but non-existing id should yield an error, not raise
        out = await _fetch_tool("programme:999999")
        assert isinstance(out, dict)
        assert "error" in out

    with app.app_context():
        asyncio.run(run())

