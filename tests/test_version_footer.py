from config.version import __version__


def test_version_in_footer_on_login_page(client):
    """
    The login page extends base.html which renders the version in the footer.
    Ensure the current application version appears in the rendered HTML.
    """
    resp = client.get('/login')
    assert resp.status_code == 200

    html = resp.data.decode('utf-8')
    # Basic presence checks
    assert "Version:" in html
    assert __version__ in html

