"""prorrogas_tec: periodo de Prórrogas de cada semestre

Escrita a mano, junto con `models/period.py`: el CI arma el esquema con `create_all`
y dev/prod con Alembic, asi que las restricciones se declaran AQUI y en el modelo
con el mismo nombre.

Que hace
--------
Crea `prorrogas_periods`: una fila por semestre de core con la ventana de solicitudes
y las dos fechas comunes de pago. Dos ventanas no pueden encimarse (EXCLUDE).

Downgrade
---------
Borra la tabla y sus datos.

Revision ID: pr20261108a
Revises: pr20261101a
Create Date: 2026-11-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision = "pr20261108a"
down_revision = "pr20261101a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prorrogas_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("core_academic_periods.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("opens_on", sa.Date(), nullable=False),
        sa.Column("closes_on", sa.Date(), nullable=False),
        sa.Column("payment_1_on", sa.Date(), nullable=False),
        sa.Column("payment_2_on", sa.Date(), nullable=False),
        sa.Column("updated_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("period_id", name="uq_prorrogas_periods_semestre"),
        sa.CheckConstraint("closes_on > opens_on", name="ck_prorrogas_periods_ventana"),
        sa.CheckConstraint("payment_1_on > opens_on AND payment_2_on > payment_1_on", name="ck_prorrogas_periods_pagos"),
        ExcludeConstraint((sa.text("daterange(opens_on, closes_on, '[]')"), "&&"),
                          name="ex_prorrogas_periods_ventana", using="gist"),
    )


def downgrade():
    op.drop_table("prorrogas_periods")
