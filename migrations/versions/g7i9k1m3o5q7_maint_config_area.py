"""maint config: technical areas catalog

Revision ID: g7i9k1m3o5q7
Revises: f6h8j0l2n4p6
Create Date: 2026-05-18

Agrega tabla para Fase 5 del plan de Configuración del módulo Maint:
  - Catálogo de áreas técnicas (maint_area)

La tabla se enlaza con maint_technician_areas por código (campo String),
sin FK, para preservar compatibilidad con los valores existentes en
MaintTechnicianArea.area_code hasta que sea refactorizado.
"""
from alembic import op
import sqlalchemy as sa


revision = 'g7i9k1m3o5q7'
down_revision = 'f6h8j0l2n4p6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maint_area — catálogo de áreas técnicas
    # Valores estándar: TRANSPORT, ELECTRICAL, CARPENTRY, AC,
    #                   GARDENING, GENERAL, PAINTING
    # ------------------------------------------------------------------
    op.create_table(
        'maint_area',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(30), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('icon', sa.String(60), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_maint_area_code'),
    )
    op.create_index('ix_maint_area_code', 'maint_area', ['code'], unique=True)
    op.create_index('ix_maint_area_is_active', 'maint_area', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_maint_area_is_active', table_name='maint_area')
    op.drop_index('ix_maint_area_code', table_name='maint_area')
    op.drop_table('maint_area')
