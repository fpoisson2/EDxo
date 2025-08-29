from flask_login import current_user
from sqlalchemy import event
from datetime import datetime, timezone
import sqlalchemy.exc
from ..extensions import db

def process_changes(mapper, target, operation):
    changes = {}

    # Helper to sanitize a single scalar value
    def sanitize_scalar(value):
        # Preserve JSON-native scalars
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        # SQLAlchemy model instance: prefer its primary key if available
        if hasattr(value, "id"):
            try:
                return getattr(value, "id")
            except Exception:
                return str(value)
        # Fallback to string for anything non-serializable
        return str(value)

    if operation == 'INSERT':
        # Pour les INSERT, capturez les nouvelles valeurs (colonnes simples) en tant que chaînes
        changes['new_values'] = {
            column.key: str(getattr(target, column.key))
            for column in mapper.columns
            if hasattr(target, column.key) and getattr(target, column.key) is not None
        }
    elif operation == 'UPDATE':
        # Pour les UPDATE, capturez les anciennes et nouvelles valeurs (colonnes uniquement)
        state = db.inspect(target)
        changes['old_values'] = {}
        changes['new_values'] = {}
        for column in mapper.columns:
            try:
                history = state.attrs[column.key].history
            except Exception:
                continue
            if history.has_changes():
                old_val = history.deleted[0] if history.deleted else None
                new_val = history.added[0] if history.added else None
                changes['old_values'][column.key] = sanitize_scalar(old_val)
                changes['new_values'][column.key] = sanitize_scalar(new_val)
    elif operation == 'DELETE':
        # Pour les DELETE, capturez les anciennes valeurs (colonnes simples) en tant que chaînes
        changes['deleted_values'] = {
            column.key: str(getattr(target, column.key))
            for column in mapper.columns
            if hasattr(target, column.key) and getattr(target, column.key) is not None
        }

    # Gestion des relations si nécessaire (en enregistrant seulement des identifiants)
    for relationship in mapper.relationships:
        if hasattr(target, relationship.key):
            rel_value = getattr(target, relationship.key)
            if rel_value is not None:
                if hasattr(rel_value, 'id'):
                    if operation == 'UPDATE':
                        changes[f"{relationship.key}_id_new"] = sanitize_scalar(rel_value)
                    else:
                        changes[f"{relationship.key}_id"] = sanitize_scalar(rel_value)
                elif isinstance(rel_value, (list, tuple, set)):
                    # Only include compact representations for collections
                    changes[relationship.key] = [sanitize_scalar(item) for item in rel_value]

    return changes

def track_changes(mapper, connection, target, operation):
    from ..app.models import DBChange

    from flask_login import current_user
    
    try:
        if isinstance(target, DBChange):
            return
            
        changes = process_changes(mapper, target, operation)
        
        # Sanitize changes: convert any non-JSON types to serializable forms
        def sanitize(obj):
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                return [sanitize(item) for item in obj]
            # SQLAlchemy model instance → use its id if available, else string
            if hasattr(obj, 'id'):
                try:
                    return getattr(obj, 'id')
                except Exception:
                    return str(obj)
            # Fallback for any other non-serializable type
            return str(obj)
        clean_changes = sanitize(changes)
        connection.execute(
            DBChange.__table__.insert(),
            {
                # Utiliser un objet datetime UTC pour la colonne DateTime
                'timestamp': datetime.now(timezone.utc),
                'user_id': current_user.id if current_user and current_user.is_authenticated else None,
                'operation': operation,
                'table_name': target.__tablename__,
                'record_id': getattr(target, 'id', None),
                'changes': clean_changes
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
    from ..app.models import (
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
