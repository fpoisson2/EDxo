from src.app import db
from src.app.models import User
from src.app.routes.chat.history import add_message, get_last_messages


def test_add_and_get_history(app):
    with app.app_context():
        user = User(username='alice', password='pw', role='admin')
        db.session.add(user)
        db.session.commit()

        add_message(user.id, 'user', 'bonjour')
        add_message(user.id, 'assistant', 'salut')

        messages = get_last_messages(user.id, limit=5)
        assert len(messages) == 2
        assert [m.role for m in messages] == ['user', 'assistant']
