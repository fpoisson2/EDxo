"""add last_openai_response_model column"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3a3d2f1c4b05'
down_revision = 'b6d007ad4e76'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('User', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_openai_response_model', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('User', schema=None) as batch_op:
        batch_op.drop_column('last_openai_response_model')
