
def test_chat_route_protected(client):
    response = client.get('/chat')
    assert response.status_code in (301, 302)
    assert 'login' in response.headers.get('Location', '')
