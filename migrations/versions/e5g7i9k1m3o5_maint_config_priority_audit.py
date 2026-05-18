"""maint config: priority catalog and config change log

Revision ID: e5g7i9k1m3o5
Revises: d4f6h8j0l2n4
Create Date: 2026-05-18

Agrega tablas para Fase 3 del plan de Configuración del módulo Maint:
  - Catálogo de prioridades editables con SLA (maint_priority)
  - Auditoría de cambios de configuración (maint_config_change_log)

Tablas creadas:
  - maint_priority
  - maint_config_change_log
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5g7i9k1m3o5'
down_revision = 'd4f6h8j0l2n4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maint_priority — catálogo de prioridades y SLA configurables
    # El campo sla_hours reemplaza el dict SLA_HOURS hardcoded en
    # ticket.py (la migración de ticket_service.py lo usará).
    # ------------------------------------------------------------------
    op.create_table(
        'maint_priority',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('badge_class', sa.String(50), nullable=True),
        sa.Column('sla_hours', sa.Integer(), nullable=False, server_default='72'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_maint_priority_code'),
    )
    op.create_index('ix_maint_priority_code', 'maint_priority', ['code'], unique=True)
    op.create_index('ix_maint_priority_is_active', 'maint_priority', ['is_active'])

    # ------------------------------------------------------------------
    # maint_config_change_log — auditoría de cambios de configuración
    # ------------------------------------------------------------------
    op.create_table(
        'maint_config_change_log',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('entity_type', sa.String(30), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('before_data', sa.JSON(), nullable=True),
        sa.Column('after_data', sa.JSON(), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['core_users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_maint_config_change_log_user_id',
                    'maint_config_change_log', ['user_id'])
    op.create_index('ix_maint_config_change_log_entity_type',
                    'maint_config_change_log', ['entity_type'])
    op.create_index('ix_maint_config_change_log_changed_at',
                    'maint_config_change_log', ['changed_at'])
    op.create_index('ix_maint_config_log_entity',
                    'maint_config_change_log',
                    ['entity_type', 'entity_id', 'changed_at'])


def downgrade() -> None:
    # Orden inverso: primero el log (sin dependencias de FK), luego priority
    op.drop_index('ix_maint_config_log_entity', table_name='maint_config_change_log')
    op.drop_index('ix_maint_config_change_log_changed_at',
                  table_name='maint_config_change_log')
    op.drop_index('ix_maint_config_change_log_entity_type',
                  table_name='maint_config_change_log')
    op.drop_index('ix_maint_config_change_log_user_id',
                  table_name='maint_config_change_log')
    op.drop_table('maint_config_change_log')

    op.drop_index('ix_maint_priority_is_active', table_name='maint_priority')
    op.drop_index('ix_maint_priority_code', table_name='maint_priority')
    op.drop_table('maint_priority')
