"""maint config: notification templates catalog

Revision ID: h2j4l6n8p0r2
Revises: g7i9k1m3o5q7
Create Date: 2026-05-18

Agrega tabla para Fase 6 del plan de Configuración del módulo Maint:
  - Catálogo de plantillas de notificación (maint_notification_template)

Permite editar desde la UI los asuntos, títulos y cuerpos de las
notificaciones transaccionales (in-app y/o email) sin despliegue de código.
"""
from alembic import op
import sqlalchemy as sa


revision = 'h2j4l6n8p0r2'
down_revision = 'g7i9k1m3o5q7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maint_notification_template — catálogo de plantillas de notificación
    # Canales estándar: inapp | email | both
    # ------------------------------------------------------------------
    op.create_table(
        'maint_notification_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(80), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False,
                  server_default=sa.text("'inapp'")),
        sa.Column('subject_template', sa.String(255), nullable=True),
        sa.Column('title_template', sa.String(255), nullable=True),
        sa.Column('body_template', sa.Text(), nullable=False),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.text('TRUE')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_by_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_id'], ['core_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_maint_notification_template_code'),
    )
    op.create_index(
        'ix_maint_notification_template_code',
        'maint_notification_template',
        ['code'],
        unique=True,
    )
    op.create_index(
        'ix_maint_notification_template_is_active',
        'maint_notification_template',
        ['is_active'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_maint_notification_template_is_active',
        table_name='maint_notification_template',
    )
    op.drop_index(
        'ix_maint_notification_template_code',
        table_name='maint_notification_template',
    )
    op.drop_table('maint_notification_template')
