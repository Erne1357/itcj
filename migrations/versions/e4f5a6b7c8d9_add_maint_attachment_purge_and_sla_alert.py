"""add_maint_attachment_purge_and_sla_alert

Revision ID: e4f5a6b7c8d9
Revises: c1d2e3f4a5b6
Create Date: 2026-05-07

Cambios:
  maint_attachments:
    - filepath: NOT NULL → NULL  (filas existentes conservan su valor)
    - is_purged: Boolean NOT NULL DEFAULT FALSE (nuevo)
    - purged_at: DateTime NULL (nuevo)
    - ix_maint_attachment_purged en (is_purged, auto_delete_at) (nuevo)

  maint_tickets:
    - sla_alert_sent_at: DateTime NULL (nuevo)
"""
from alembic import op
import sqlalchemy as sa


revision = 'e4f5a6b7c8d9'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maint_attachments — soporte de purga de archivo físico
    # ------------------------------------------------------------------

    # 1. Hacer filepath nullable (filas existentes conservan su path actual)
    op.alter_column(
        'maint_attachments', 'filepath',
        existing_type=sa.String(500),
        nullable=True,
    )

    # 2. is_purged: NOT NULL con server_default=FALSE para filas existentes
    op.add_column(
        'maint_attachments',
        sa.Column('is_purged', sa.Boolean(), nullable=False,
                  server_default=sa.text('FALSE')),
    )

    # 3. purged_at: timestamp opcional del momento de purga
    op.add_column(
        'maint_attachments',
        sa.Column('purged_at', sa.DateTime(), nullable=True),
    )

    # 4. Índice compuesto para la query de cleanup: is_purged=FALSE AND auto_delete_at < now()
    op.create_index(
        'ix_maint_attachment_purged',
        'maint_attachments',
        ['is_purged', 'auto_delete_at'],
    )

    # ------------------------------------------------------------------
    # maint_tickets — columna para rastrear envío de alerta SLA
    # ------------------------------------------------------------------

    op.add_column(
        'maint_tickets',
        sa.Column('sla_alert_sent_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    # Revertir en orden inverso

    # maint_tickets
    op.drop_column('maint_tickets', 'sla_alert_sent_at')

    # maint_attachments
    op.drop_index('ix_maint_attachment_purged', table_name='maint_attachments')
    op.drop_column('maint_attachments', 'purged_at')
    op.drop_column('maint_attachments', 'is_purged')

    # Revertir filepath a NOT NULL.
    # ADVERTENCIA: fallará si existen filas con filepath NULL (adjuntos purgados).
    # Ejecutar sólo si ningún adjunto ha sido purgado, o tras rellenar los NULLs.
    op.alter_column(
        'maint_attachments', 'filepath',
        existing_type=sa.String(500),
        nullable=False,
    )
