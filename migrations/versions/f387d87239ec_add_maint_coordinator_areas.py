"""add_maint_coordinator_areas

Revision ID: f387d87239ec
Revises: m3p5q7s9u1v3
Create Date: 2026-06-01 09:43:23.490871

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f387d87239ec'
down_revision = 'm3p5q7s9u1v3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'maint_coordinator_areas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('area_code', sa.String(length=30), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['core_users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['core_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'area_code', name='uq_maint_coordinator_areas_user_area'),
    )
    op.create_index('ix_maint_coordinator_areas_area_code', 'maint_coordinator_areas', ['area_code'], unique=False)
    op.create_index('ix_maint_coordinator_areas_user_id', 'maint_coordinator_areas', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_maint_coordinator_areas_user_id', table_name='maint_coordinator_areas')
    op.drop_index('ix_maint_coordinator_areas_area_code', table_name='maint_coordinator_areas')
    op.drop_table('maint_coordinator_areas')
