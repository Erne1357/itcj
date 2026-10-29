"""prorrogas_tec: plan de pago (parcialidades) y recibos de Caja

Escrita a mano, junto con `models/plan.py` y `models/request.py`: el CI arma el
esquema con `create_all` y dev/prod con Alembic, asi que tablas, columnas, CHECK
e indices se declaran AQUI y en los modelos con los mismos nombres.

Que hace
--------
Crea `prorrogas_installments` y `prorrogas_payments`, y agrega a
`prorrogas_requests` el monto total (con su CHECK), la confirmacion del plan y
las marcas de exportacion, aviso de desbloqueo y recordatorio.

Downgrade
---------
Quita las columnas y tablas nuevas en orden inverso (pierde los planes y recibos).

Revision ID: pr20261031a
Revises: pr20261030a
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = "pr20261031a"
down_revision = "pr20261030a"
branch_labels = None
depends_on = None

_COLS = ("last_reminded_at", "unblock_notified_at", "block_exported_at", "plan_confirmed_by_id",
         "plan_confirmed_at", "total_amount")


def upgrade():
    now = sa.text("NOW()")
    op.add_column("prorrogas_requests", sa.Column("total_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("prorrogas_requests", sa.Column("plan_confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("prorrogas_requests", sa.Column("plan_confirmed_by_id", sa.BigInteger(), nullable=True))
    op.add_column("prorrogas_requests", sa.Column("block_exported_at", sa.DateTime(), nullable=True))
    op.add_column("prorrogas_requests", sa.Column("unblock_notified_at", sa.DateTime(), nullable=True))
    op.add_column("prorrogas_requests", sa.Column("last_reminded_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_prorrogas_requests_plan_confirmed_by", "prorrogas_requests", "core_users",
                          ["plan_confirmed_by_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_prorrogas_requests_total", "prorrogas_requests",
                               "total_amount IS NULL OR total_amount > 0")

    op.create_table(
        "prorrogas_installments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("number BETWEEN 1 AND 3", name="ck_prorrogas_installments_number"),
        sa.CheckConstraint("amount > 0", name="ck_prorrogas_installments_amount"),
        sa.ForeignKeyConstraint(["request_id"], ["prorrogas_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_prorrogas_installments_vigente", "prorrogas_installments", ["request_id", "number"],
                    unique=True, postgresql_where=sa.text("superseded_at IS NULL"))

    op.create_table(
        "prorrogas_payments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(10), server_default="app", nullable=False),
        sa.Column("folio", sa.String(40), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("recorded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by_id", sa.BigInteger(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("origin IN ('app','excel')", name="ck_prorrogas_payments_origin"),
        sa.CheckConstraint("amount > 0", name="ck_prorrogas_payments_amount"),
        sa.ForeignKeyConstraint(["request_id"], ["prorrogas_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voided_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_prorrogas_payments_folio_vigente", "prorrogas_payments", ["folio"], unique=True,
                    postgresql_where=sa.text("folio IS NOT NULL AND voided_at IS NULL"))
    op.create_index("ix_prorrogas_payments_solicitud", "prorrogas_payments", ["request_id"])


def downgrade():
    op.drop_table("prorrogas_payments")
    op.drop_table("prorrogas_installments")
    op.drop_constraint("ck_prorrogas_requests_total", "prorrogas_requests", type_="check")
    op.drop_constraint("fk_prorrogas_requests_plan_confirmed_by", "prorrogas_requests", type_="foreignkey")
    for c in _COLS:
        op.drop_column("prorrogas_requests", c)
