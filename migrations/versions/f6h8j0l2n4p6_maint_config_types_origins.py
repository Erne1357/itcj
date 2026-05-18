"""maint config: maintenance type and service origin catalogs

Revision ID: f6h8j0l2n4p6
Revises: e5g7i9k1m3o5
Create Date: 2026-05-18

Agrega tablas para Fase 4 del plan de Configuración del módulo Maint:
  - Catálogo de tipos de mantenimiento (maint_maintenance_type)
  - Catálogo de orígenes del servicio   (maint_service_origin)

Ambas tablas se enlazan con maint_ticket por código (campo String),
sin FK, para mantener compatibilidad con los valores hardcodeados
hasta que ticket_service.py sea refactorizado.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6h8j0l2n4p6'
down_revision = 'e5g7i9k1m3o5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maint_maintenance_type — catálogo de tipos de mantenimiento
    # Valores estándar: PREVENTIVO, CORRECTIVO
    # ------------------------------------------------------------------
    op.create_table(
        'maint_maintenance_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('label', sa.String(60), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_maint_maintenance_type_code'),
    )
    op.create_index('ix_maint_maintenance_type_code',
                    'maint_maintenance_type', ['code'], unique=True)
    op.create_index('ix_maint_maintenance_type_is_active',
                    'maint_maintenance_type', ['is_active'])

    # ------------------------------------------------------------------
    # maint_service_origin — catálogo de orígenes del servicio
    # Valores estándar: INTERNO, EXTERNO
    # ------------------------------------------------------------------
    op.create_table(
        'maint_service_origin',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('label', sa.String(60), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_maint_service_origin_code'),
    )
    op.create_index('ix_maint_service_origin_code',
                    'maint_service_origin', ['code'], unique=True)
    op.create_index('ix_maint_service_origin_is_active',
                    'maint_service_origin', ['is_active'])


def downgrade() -> None:
    # Orden inverso al upgrade
    op.drop_index('ix_maint_service_origin_is_active',
                  table_name='maint_service_origin')
    op.drop_index('ix_maint_service_origin_code',
                  table_name='maint_service_origin')
    op.drop_table('maint_service_origin')

    op.drop_index('ix_maint_maintenance_type_is_active',
                  table_name='maint_maintenance_type')
    op.drop_index('ix_maint_maintenance_type_code',
                  table_name='maint_maintenance_type')
    op.drop_table('maint_maintenance_type')
