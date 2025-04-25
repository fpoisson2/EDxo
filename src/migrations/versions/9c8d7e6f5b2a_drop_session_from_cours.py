"""
Drop the old session column from Cours now that sessions are per association.

Revision ID: 9c8d7e6f5b2a
Revises: 6d5a4b3c2e1f
Create Date: 2025-04-25 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9c8d7e6f5b2a'
down_revision = '6d5a4b3c2e1f'
branch_labels = None
depends_on = None

def upgrade():
    # Drop the legacy session column on Cours
    with op.batch_alter_table('Cours') as batch_op:
        batch_op.drop_column('session')

def downgrade():
    # Recreate the session column with default 0
    with op.batch_alter_table('Cours') as batch_op:
        batch_op.add_column(
            sa.Column('session', sa.Integer(), nullable=False, server_default='0')
        )
    # Backfill using first association value
    op.execute(
        """
        UPDATE Cours
        SET session = (
            SELECT session
            FROM Cours_Programme
            WHERE Cours_Programme.cours_id = Cours.id
            LIMIT 1
        )
        """
    )
    with op.batch_alter_table('Cours') as batch_op:
        batch_op.alter_column('session', server_default=None)