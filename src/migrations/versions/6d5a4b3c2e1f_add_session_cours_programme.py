"""
Add session column to association table Cours_Programme and migrate existing data

Revision ID: 6d5a4b3c2e1f
Revises: 145ed415b3f9
Create Date: 2025-04-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '6d5a4b3c2e1f'
down_revision = '145ed415b3f9'
branch_labels = None
depends_on = None

def upgrade():
    # Add 'session' column to Cours_Programme with a default of 0
    op.add_column(
        'Cours_Programme',
        sa.Column('session', sa.Integer(), nullable=False, server_default='0')
    )
    # Migrate existing data: set association.session = Cours.session
    op.execute(
        """
        UPDATE Cours_Programme
        SET session = (
            SELECT session FROM Cours WHERE Cours.id = Cours_Programme.cours_id
        )
        """
    )
    # Remove server default now that data is populated
    with op.batch_alter_table('Cours_Programme') as batch_op:
        batch_op.alter_column('session', server_default=None)

def downgrade():
    # Remove the 'session' column
    with op.batch_alter_table('Cours_Programme') as batch_op:
        batch_op.drop_column('session')