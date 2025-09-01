from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3a2b1c4d5e6f'
down_revision = 'd420453e4321'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'docx_schema_pages' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('docx_schema_pages')}
        if 'markdown_content' not in cols:
            with op.batch_alter_table('docx_schema_pages', schema=None) as batch_op:
                batch_op.add_column(sa.Column('markdown_content', sa.Text(), nullable=True))

def downgrade():
    with op.batch_alter_table('docx_schema_pages', schema=None) as batch_op:
        batch_op.drop_column('markdown_content')
