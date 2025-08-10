"""add chat model config

Revision ID: 0d1e92a8b7cd
Revises: 19b209438a4e
Create Date: 2025-05-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0d1e92a8b7cd'
down_revision = '19b209438a4e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'chat_model_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_model', sa.String(length=64), nullable=False, server_default='gpt-4.1-mini'),
        sa.Column('tool_model', sa.String(length=64), nullable=False, server_default='gpt-4.1-mini'),
        sa.Column('reasoning_effort', sa.String(length=16), nullable=True),
        sa.Column('verbosity', sa.String(length=16), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('chat_model_config')
