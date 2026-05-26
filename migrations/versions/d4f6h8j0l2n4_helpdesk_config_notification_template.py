"""helpdesk config: notification template catalog

Revision ID: d4f6h8j0l2n4
Revises: c3e5g7i9k1m3
Create Date: 2026-05-11

Agrega tabla para Fase 6 (plantillas de notificación editables desde la UI)
del plan de Configuración del módulo Helpdesk.

Tablas creadas:
  - helpdesk_notification_template
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4f6h8j0l2n4'
down_revision = 'c3e5g7i9k1m3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # helpdesk_notification_template — plantillas de notificación
    # editables desde la UI de configuración del helpdesk.
    # Las plantillas se crean por seed; la UI solo permite edit + toggle.
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_notification_template',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(80), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('channel', sa.String(20), nullable=False,
                  server_default='inapp'),
        sa.Column('subject_template', sa.String(255), nullable=True),
        sa.Column('body_template', sa.Text(), nullable=False),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_by_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ['updated_by_id'], ['core_users.id'],
            name='fk_notification_template_updated_by',
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_helpdesk_notification_template_code'),
    )
    op.create_index(
        'ix_helpdesk_notification_template_code',
        'helpdesk_notification_template', ['code'], unique=True,
    )
    op.create_index(
        'ix_helpdesk_notification_template_updated_by_id',
        'helpdesk_notification_template', ['updated_by_id'],
    )
    op.create_index(
        'ix_helpdesk_notification_template_active_code',
        'helpdesk_notification_template', ['is_active', 'code'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_helpdesk_notification_template_active_code',
        table_name='helpdesk_notification_template',
    )
    op.drop_index(
        'ix_helpdesk_notification_template_updated_by_id',
        table_name='helpdesk_notification_template',
    )
    op.drop_index(
        'ix_helpdesk_notification_template_code',
        table_name='helpdesk_notification_template',
    )
    op.drop_table('helpdesk_notification_template')
