"""add ai_model to plan de cours prompt settings

Revision ID: 09fb8fece955
Revises: 0d1e92a8b7cd
Create Date: 2025-08-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '09fb8fece955'
down_revision = '0d1e92a8b7cd'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('plan_de_cours_prompt_settings',
                  sa.Column('ai_model', sa.String(length=50), nullable=False, server_default='gpt-4o'))


def downgrade():
    op.drop_column('plan_de_cours_prompt_settings', 'ai_model')
