from src.app import db
from src.utils.db_tracking import process_changes


class Dummy(db.Model):
    __tablename__ = 'dummy'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    value = db.Column(db.Integer)


def test_process_changes_insert(app):
    obj = Dummy(name='alpha', value=1)
    db.session.add(obj)
    db.session.flush()
    changes = process_changes(Dummy.__mapper__, obj, 'INSERT')
    assert 'new_values' in changes
    assert changes['new_values'] == {
        'id': str(obj.id),
        'name': 'alpha',
        'value': '1',
    }


def test_process_changes_update(app):
    obj = Dummy(name='alpha', value=1)
    db.session.add(obj)
    db.session.commit()
    obj = Dummy.query.first()
    obj.name = 'beta'
    obj.value = 2
    changes = process_changes(Dummy.__mapper__, obj, 'UPDATE')
    assert changes['old_values'] == {'name': 'alpha', 'value': 1}
    assert changes['new_values'] == {'name': 'beta', 'value': 2}


def test_process_changes_delete(app):
    obj = Dummy(name='alpha', value=1)
    db.session.add(obj)
    db.session.commit()
    obj = Dummy.query.first()
    db.session.delete(obj)
    changes = process_changes(Dummy.__mapper__, obj, 'DELETE')
    assert changes['deleted_values'] == {
        'id': str(obj.id),
        'name': 'alpha',
        'value': '1',
    }
