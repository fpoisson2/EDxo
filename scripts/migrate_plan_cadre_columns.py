"""Migration utilitaire: transfère les colonnes PlanCadre vers DataSchemaRecord."""

import argparse
from contextlib import suppress

from sqlalchemy.orm import load_only, selectinload

from src.app import create_app, db
from src.app.models import (
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    PlanCadreSavoirEtre,
)
from src.utils.schema_manager import PlanCadreSchemaManager


RELATION_KEYS = {
    'capacites': PlanCadreCapacites,
    'objets_cibles': PlanCadreObjetsCibles,
    'cours_relies': PlanCadreCoursRelies,
    'cours_prealables': PlanCadreCoursPrealables,
    'cours_corequis': PlanCadreCoursCorequis,
    'competences_certifiees': PlanCadreCompetencesCertifiees,
    'competences_developpees': PlanCadreCompetencesDeveloppees,
    'savoirs_etre': PlanCadreSavoirEtre,
}


def migrate_plan_cadre_columns(
    dry_run: bool = False,
    overwrite: bool = False,
    purge_relations: bool = False,
) -> None:
    """Copie les colonnes et relations PlanCadre dans DataSchemaRecord.data.

    Args:
        dry_run: aucune écriture finale si True.
        overwrite: remplace les valeurs JSON existantes.
        purge_relations: supprime les colonnes SQL et les relations après migration.
    """

    app = create_app()
    with app.app_context():
        manager = PlanCadreSchemaManager()
        manager.ensure_schema()
        column_keys = [name for name, _label in manager.column_choices()]
        column_attrs = [getattr(PlanCadre, key) for key in column_keys if hasattr(PlanCadre, key)]

        relationship_loaders = [
            selectinload(PlanCadre.capacites)
            .selectinload(PlanCadreCapacites.savoirs_necessaires),
            selectinload(PlanCadre.capacites)
            .selectinload(PlanCadreCapacites.savoirs_faire),
            selectinload(PlanCadre.capacites)
            .selectinload(PlanCadreCapacites.moyens_evaluation),
            selectinload(PlanCadre.objets_cibles),
            selectinload(PlanCadre.cours_relies),
            selectinload(PlanCadre.cours_prealables),
            selectinload(PlanCadre.cours_corequis),
            selectinload(PlanCadre.competences_certifiees),
            selectinload(PlanCadre.competences_developpees),
            selectinload(PlanCadre.savoirs_etre),
        ]

        options = []
        if column_attrs:
            options.append(load_only(*column_attrs))
        options.extend(relationship_loaders)
        query = PlanCadre.query.options(*options) if options else PlanCadre.query
        total = updated = skipped = 0

        for plan in query:  # type: ignore[assignment]
            total += 1
            record = manager.record_for_plan(plan)
            payload = dict(record.data or {})
            changed = False

            for key in column_keys:
                value = getattr(plan, key, None)
                if value in (None, ""):
                    continue

                existing = payload.get(key)
                if existing in (None, "") or overwrite:
                    if existing == value:
                        continue
                    payload[key] = value
                    changed = True
                else:
                    skipped += 1

            rel_changed = _migrate_relations(plan, payload, overwrite)
            changed = changed or rel_changed

            if changed:
                updated += 1
                record.data = payload
                db.session.add(record)

                if purge_relations and not dry_run:
                    _purge_plan_columns(plan, column_keys)
                    _purge_plan_relations(plan)

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

        print(f"Plans inspectés : {total}")
        print(f"Plans mis à jour : {updated}")
        if skipped:
            print(f"Valeurs existantes préservées (non overwritées) : {skipped}")
        if purge_relations:
            print("Purge effectuée pour les plans migrés." if not dry_run else "Purge simulée (dry-run).")


def _migrate_relations(plan: PlanCadre, payload: dict, overwrite: bool) -> bool:
    changed = False

    def should_write(key: str) -> bool:
        if overwrite:
            return True
        return key not in payload or payload.get(key) in (None, "", [], {})

    if should_write('capacites'):
        payload['capacites'] = [
            {
                'capacite': cap.capacite,
                'description_capacite': cap.description_capacite,
                'ponderation_min': cap.ponderation_min,
                'ponderation_max': cap.ponderation_max,
                'savoirs_necessaires': [sn.texte for sn in cap.savoirs_necessaires],
                'savoirs_faire': [
                    {
                        'texte': sf.texte,
                        'cible': sf.cible,
                        'seuil_reussite': sf.seuil_reussite,
                    }
                    for sf in cap.savoirs_faire
                ],
                'moyens_evaluation': [me.texte for me in cap.moyens_evaluation],
            }
            for cap in plan.capacites
        ]
        changed = True

    mapping = {
        'objets_cibles': plan.objets_cibles,
        'cours_relies': plan.cours_relies,
        'cours_prealables': plan.cours_prealables,
        'cours_corequis': plan.cours_corequis,
        'competences_certifiees': plan.competences_certifiees,
        'competences_developpees': plan.competences_developpees,
    }

    for key, items in mapping.items():
        if should_write(key):
            payload[key] = [
                {
                    'texte': getattr(item, 'texte', None),
                    'description': getattr(item, 'description', None),
                }
                for item in items
            ]
            changed = True

    if should_write('savoirs_etre'):
        payload['savoirs_etre'] = [item.texte for item in plan.savoirs_etre]
        changed = True

    return changed


def _purge_plan_columns(plan: PlanCadre, column_keys: list[str]) -> None:
    for key in column_keys:
        if hasattr(plan, key):
            setattr(plan, key, None)


def _purge_plan_relations(plan: PlanCadre) -> None:
    for rel_name, model in RELATION_KEYS.items():
        items = getattr(plan, rel_name, None)
        if not items:
            continue
        for item in list(items):
            db.session.delete(item)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transfère les colonnes PlanCadre vers DataSchemaRecord.data"
    )
    parser.add_argument("--dry-run", action="store_true", help="Aucun commit en base")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remplace les valeurs JSON existantes",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Supprime colonnes et relations après migration (⚠ destructif)",
    )
    args = parser.parse_args()

    migrate_plan_cadre_columns(
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        purge_relations=args.purge,
    )


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        main()
