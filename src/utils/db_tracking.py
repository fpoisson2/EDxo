from flask_login import current_user
from sqlalchemy import event
from datetime import datetime
import sqlalchemy.exc

def process_changes(mapper, target, operation):
    changes = {}
    
    if operation == 'INSERT':
        # Pour les INSERT, capturez les nouvelles valeurs
        changes['new_values'] = {
            column.key: str(getattr(target, column.key))
            for column in mapper.columns
            if hasattr(target, column.key) and getattr(target, column.key) is not None
        }
    elif operation == 'UPDATE':
        # Pour les UPDATE, capturez les anciennes et nouvelles valeurs
        state = db.inspect(target)
        changes['old_values'] = {}
        changes['new_values'] = {}
        for attr in state.attrs:
            if attr.history.has_changes():
                changes['old_values'][attr.key] = attr.history.deleted[0] if attr.history.deleted else None
                changes['new_values'][attr.key] = attr.history.added[0] if attr.history.added else None
    elif operation == 'DELETE':
        # Pour les DELETE, capturez les anciennes valeurs
        changes['deleted_values'] = {
            column.key: str(getattr(target, column.key))
            for column in mapper.columns
            if hasattr(target, column.key) and getattr(target, column.key) is not None
        }
    
    # Gestion des relations si nécessaire
    for relationship in mapper.relationships:
        if hasattr(target, relationship.key):
            rel_value = getattr(target, relationship.key)
            if rel_value is not None:
                if hasattr(rel_value, 'id'):
                    if operation == 'UPDATE':
                        changes[f"{relationship.key}_id_new"] = str(rel_value.id)
                        # Vous pourriez vouloir capturer l'ancien ID si pertinent
                    else:
                        changes[f"{relationship.key}_id"] = str(rel_value.id)
                elif isinstance(rel_value, list):
                    changes[relationship.key] = [str(item.id) for item in rel_value if hasattr(item, 'id')]
    
    return changes

def track_changes(mapper, connection, target, operation):
    from app.models import db, DBChange
    from flask_login import current_user
    
    try:
        if isinstance(target, DBChange):
            return
            
        changes = process_changes(mapper, target, operation)
        
        connection.execute(
            DBChange.__table__.insert(),
            {
                'timestamp': datetime.utcnow(),
                'user_id': current_user.id if current_user and current_user.is_authenticated else None,
                'operation': operation,
                'table_name': target.__tablename__,
                'record_id': getattr(target, 'id', None),
                'changes': changes
            }
        )
    except Exception as e:
        print(f"Error tracking {operation}: {e}")

def track_insert(mapper, connection, target):
    track_changes(mapper, connection, target, 'INSERT')

def track_update(mapper, connection, target):
    track_changes(mapper, connection, target, 'UPDATE')

def track_delete(mapper, connection, target):
    track_changes(mapper, connection, target, 'DELETE')

def init_change_tracking(db):
    from app.models import (
        User, Cours, Programme, PlanCadre, PlanDeCours, Department,
        Competence, ElementCompetence, ElementCompetenceCriteria,
        FilConducteur, CoursPrealable, CoursCorequis,
        CompetenceParCours, ElementCompetenceParCours,
        PlanCadreCapacites, PlanCadreSavoirEtre,
        PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
        PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations,
        PlanDeCoursEvaluationsCapacites, PlanCadreCoursCorequis,
        PlanCadreCoursPrealables, PlanCadreCompetencesCertifiees,
        PlanCadreCompetencesDeveloppees, PlanCadreObjetsCibles,
        PlanCadreCoursRelies, DepartmentRegles, DepartmentPIEA,
        ListeProgrammeMinisteriel, ListeCegep, GlobalGenerationSettings,
        ChatHistory, BackupConfig
    )

    models_to_track = [
        User, Cours, Programme, PlanCadre, PlanDeCours, Department,
        Competence, ElementCompetence, ElementCompetenceCriteria,
        FilConducteur, CoursPrealable, CoursCorequis,
        CompetenceParCours, ElementCompetenceParCours,
        PlanCadreCapacites, PlanCadreSavoirEtre,
        PlanDeCoursCalendrier, PlanDeCoursMediagraphie,
        PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations,
        PlanDeCoursEvaluationsCapacites, PlanCadreCoursCorequis,
        PlanCadreCoursPrealables, PlanCadreCompetencesCertifiees,
        PlanCadreCompetencesDeveloppees, PlanCadreObjetsCibles,
        PlanCadreCoursRelies, DepartmentRegles, DepartmentPIEA,
        ListeProgrammeMinisteriel, ListeCegep, GlobalGenerationSettings,
        ChatHistory, BackupConfig
    ]
    
    for model in models_to_track:
        event.listen(model, 'after_insert', track_insert)
        event.listen(model, 'before_update', track_update)  # Utiliser before_update pour capturer l'état avant la modification
        event.listen(model, 'before_delete', track_delete)