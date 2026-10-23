"""titulatec fase 6: Anexo III (folio, contador por semestre, product_label)

Escrita a mano. Spec: docs/superpowers/specs/2026-10-22-titulatec-fase6-anexo-iii-design.md §5

Que agrega
----------
- `titulatec_anexos` (un anexo por proceso, folio unico) y
  `titulatec_anexo_counters` (consecutivo por semestre).
- `titulatec_modalities.product_label` (nombre del producto final, NULL).

Downgrade (CON PERDIDA): borra las dos tablas y la columna.

Revision ID: tt20261022d
Revises: tt20261022c
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261022d"
down_revision = "tt20261022c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.create_table(
        "titulatec_anexos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("titulatec_processes.id"), nullable=False),
        sa.Column("folio", sa.String(20), nullable=False),
        sa.Column("semester", sa.String(5), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("issued_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True),
        sa.UniqueConstraint("process_id", name="uq_titulatec_anexos_process"),
        sa.UniqueConstraint("folio", name="uq_titulatec_anexos_folio"),
    )

    op.create_table(
        "titulatec_anexo_counters",
        sa.Column("semester", sa.String(5), primary_key=True),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column("titulatec_modalities", sa.Column("product_label", sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column("titulatec_modalities", "product_label")
    op.drop_table("titulatec_anexo_counters")
    op.drop_table("titulatec_anexos")
