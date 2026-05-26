"""helpdesk config: priority and config_change_log

Revision ID: a1c3e5g7i9k1
Revises: e4f5a6b7c8d9
Create Date: 2026-05-08

Agrega tablas para Fase 3 (catálogo de prioridades editables con SLA)
y Fase 7 (auditoría de cambios de configuración) del plan de Configuración
del módulo Helpdesk.

Tablas creadas:
  - helpdesk_priority
  - helpdesk_config_change_log
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c3e5g7i9k1'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # helpdesk_priority — catálogo de prioridades y SLA
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_priority',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('badge_class', sa.String(50), nullable=True),
        sa.Column('sla_hours', sa.Integer(), nullable=False, server_default='72'),
        sa.Column('display_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_helpdesk_priority_code'),
    )
    op.create_index('ix_helpdesk_priority_code', 'helpdesk_priority', ['code'], unique=True)
    op.create_index('ix_helpdesk_priority_is_active', 'helpdesk_priority', ['is_active'])

    # ------------------------------------------------------------------
    # helpdesk_config_change_log — auditoría de cambios de configuración
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_config_change_log',
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
    op.create_index('ix_helpdesk_config_change_log_user_id',
                    'helpdesk_config_change_log', ['user_id'])
    op.create_index('ix_helpdesk_config_change_log_entity_type',
                    'helpdesk_config_change_log', ['entity_type'])
    op.create_index('ix_helpdesk_config_change_log_changed_at',
                    'helpdesk_config_change_log', ['changed_at'])
    op.create_index('ix_config_log_entity',
                    'helpdesk_config_change_log',
                    ['entity_type', 'entity_id', 'changed_at'])


def downgrade() -> None:
    op.drop_index('ix_config_log_entity', table_name='helpdesk_config_change_log')
    op.drop_index('ix_helpdesk_config_change_log_changed_at',
                  table_name='helpdesk_config_change_log')
    op.drop_index('ix_helpdesk_config_change_log_entity_type',
                  table_name='helpdesk_config_change_log')
    op.drop_index('ix_helpdesk_config_change_log_user_id',
                  table_name='helpdesk_config_change_log')
    op.drop_table('helpdesk_config_change_log')

    op.drop_index('ix_helpdesk_priority_is_active', table_name='helpdesk_priority')
    op.drop_index('ix_helpdesk_priority_code', table_name='helpdesk_priority')
    op.drop_table('helpdesk_priority')
