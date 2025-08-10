"""add last_openai_response_model

Revision ID: c8b9b4a9820d
Revises: b6d007ad4e76
Create Date: 2025-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c8b9b4a9820d'
down_revision = 'b6d007ad4e76'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('User', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_openai_response_model', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('User', schema=None) as batch_op:
        batch_op.drop_column('last_openai_response_model')
