"""add dynamic plan cadre schema tables

Revision ID: 1f92dd1d0b21
Revises: d420453e4321
Create Date: 2024-12-09 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f92dd1d0b21'
down_revision = 'd420453e4321'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'data_schemas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_data_schema_slug')
    )

    op.create_table(
        'data_schema_sections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schema_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schema_id'], ['data_schemas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schema_id', 'key', name='uq_schema_section_key')
    )

    op.create_table(
        'data_schema_fields',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schema_id', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('help_text', sa.Text(), nullable=True),
        sa.Column('field_type', sa.String(length=32), nullable=False, server_default='textarea'),
        sa.Column('storage', sa.String(length=16), nullable=False, server_default='extra'),
        sa.Column('storage_column', sa.String(length=64), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('placeholder', sa.String(length=255), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schema_id'], ['data_schemas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['section_id'], ['data_schema_sections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schema_id', 'key', name='uq_schema_field_key')
    )

    op.create_table(
        'data_schema_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schema_id', sa.Integer(), nullable=False),
        sa.Column('owner_type', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schema_id'], ['data_schemas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schema_id', 'owner_type', 'owner_id', name='uq_schema_record_owner')
    )


def downgrade():
    op.drop_table('data_schema_records')
    op.drop_table('data_schema_fields')
    op.drop_table('data_schema_sections')
    op.drop_table('data_schemas')
