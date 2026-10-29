"""titulatec fase 6 v2: entrega del Anexo III (listo para recoger, reimpresion)

Escrita a mano. Spec: docs/superpowers/specs/2026-10-29-titulatec-fase6-anexo-entrega-design.md §5

Que agrega
----------
`titulatec_anexos`: `ready_at`, `ready_by_id` (FK core_users), `pickup_note`,
`reprint_reason` y `reprint_requested_at`, todas NULL. Sin backfill: un proceso
en la fase 6 sin escaneo queda «En preparacion».

Downgrade (CON PERDIDA): borra las cinco columnas.

Revision ID: tt20261029a
Revises: tt20261022d
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261029a"
down_revision = "tt20261022d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("titulatec_anexos", sa.Column("ready_at", sa.DateTime(), nullable=True))
    op.add_column("titulatec_anexos", sa.Column(
        "ready_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True))
    op.add_column("titulatec_anexos", sa.Column("pickup_note", sa.String(300), nullable=True))
    op.add_column("titulatec_anexos", sa.Column("reprint_reason", sa.String(500), nullable=True))
    op.add_column("titulatec_anexos", sa.Column("reprint_requested_at", sa.DateTime(),
                                                nullable=True))


def downgrade() -> None:
    op.drop_column("titulatec_anexos", "reprint_requested_at")
    op.drop_column("titulatec_anexos", "reprint_reason")
    op.drop_column("titulatec_anexos", "pickup_note")
    op.drop_column("titulatec_anexos", "ready_by_id")
    op.drop_column("titulatec_anexos", "ready_at")
