"""helpdesk config: area catalog

Revision ID: c3e5g7i9k1m3
Revises: b2d4f6h8j0l2
Create Date: 2026-05-11

Agrega tabla para Fase 5 (catálogo de áreas editable) del plan de
Configuración del módulo Helpdesk.

Tablas creadas:
  - helpdesk_area
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3e5g7i9k1m3'
down_revision = 'b2d4f6h8j0l2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # helpdesk_area — catálogo de áreas con metadatos editables
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_area',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(30), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('icon', sa.String(60), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_helpdesk_area_code'),
    )
    op.create_index('ix_helpdesk_area_code',
                    'helpdesk_area', ['code'], unique=True)
    op.create_index('ix_helpdesk_area_is_active',
                    'helpdesk_area', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_helpdesk_area_is_active',
                  table_name='helpdesk_area')
    op.drop_index('ix_helpdesk_area_code',
                  table_name='helpdesk_area')
    op.drop_table('helpdesk_area')
