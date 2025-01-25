from flask_login import current_user
from sqlalchemy import event
from datetime import datetime

def track_changes(mapper, connection, target):
    from models import db, DBChange, User, Cours, Programme, PlanCadre, PlanDeCours, Department
    
    try:
        # Skip tracking for DBChange model itself to avoid recursion
        if isinstance(target, DBChange):
            return
            
        change = DBChange(
            user_id=current_user.id if current_user and current_user.is_authenticated else None,
            table_name=target.__tablename__,
            record_id=getattr(target, 'id', None)
        )
        
        if connection._execution_options.get('synchronize_session', True):
            if not hasattr(target, '_sa_instance_state'):
                change.operation = 'INSERT'
            elif target._sa_instance_state.deleted:
                change.operation = 'DELETE'
            else:
                change.operation = 'UPDATE'
                change.changes = {
                    key: str(getattr(target, key))
                    for key in target._sa_instance_state.committed_state.keys()
                }
        
        db.session.add(change)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error tracking changes: {e}")

def init_change_tracking(db):
    from models import User, Cours, Programme, PlanCadre, PlanDeCours, Department

    models_to_track = [
        User, 
        Cours, 
        Programme, 
        PlanCadre, 
        PlanDeCours, 
        Department
    ]
    
    for model in models_to_track:
        event.listen(model, 'after_insert', track_changes)
        event.listen(model, 'after_update', track_changes)
        event.listen(model, 'after_delete', track_changes)