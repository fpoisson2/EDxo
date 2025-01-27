"""Remove unique constraint on capacite_id

Revision ID: a980783ec51d
Revises: 18cb5c536f76
Create Date: 2025-01-27 13:26:49.507221

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a980783ec51d'
down_revision = '18cb5c536f76'
branch_labels = None
depends_on = None


def upgrade():
    # Pour SQLite, on doit recréer la table
    # Sauvegarde des données
    op.execute('CREATE TABLE evaluation_savoirfaire_backup AS SELECT * FROM evaluation_savoirfaire')
    
    # Suppression de l'ancienne table
    op.drop_table('evaluation_savoirfaire')
    
    # Création de la nouvelle table sans la contrainte unique sur capacite_id
    op.create_table('evaluation_savoirfaire',
        sa.Column('evaluation_id', sa.Integer(), nullable=False),
        sa.Column('capacite_id', sa.Integer(), nullable=True),
        sa.Column('savoir_faire_id', sa.Integer(), nullable=False),
        sa.Column('selected', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['capacite_id'], ['PlanCadreCapacites.id'], name='fk_evaluation_savoirfaire_capacite'),
        sa.ForeignKeyConstraint(['evaluation_id'], ['PlanDeCoursEvaluations.id'], name='fk_evaluation_savoirfaire_evaluation'),
        sa.ForeignKeyConstraint(['savoir_faire_id'], ['PlanCadreCapaciteSavoirsFaire.id'], name='fk_evaluation_savoirfaire_savoirfaire'),
        sa.PrimaryKeyConstraint('evaluation_id', 'savoir_faire_id', name='pk_evaluation_savoirfaire')
    )
    
    # Restauration des données
    op.execute('INSERT INTO evaluation_savoirfaire SELECT * FROM evaluation_savoirfaire_backup')
    
    # Suppression de la table temporaire
    op.execute('DROP TABLE evaluation_savoirfaire_backup')

def downgrade():
    # Si vous avez besoin de revenir en arrière
    op.create_unique_constraint('uq_evaluation_capacite', 'evaluation_savoirfaire', ['evaluation_id', 'capacite_id'])