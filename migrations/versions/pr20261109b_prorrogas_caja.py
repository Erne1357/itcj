"""prorrogas_tec: recibo escaneado de Caja en la parcialidad

El recibo escaneado cuelga de la parcialidad (`prorrogas_installments`) y no del
recibo de Caja (`prorrogas_payments`): asi sobrevive a una anulacion del pago.
Solo agrega dos columnas; no toca datos.

Downgrade: quita las dos columnas (se pierde la ruta de los recibos subidos).

Revision ID: pr20261109b
Revises: pr20261109a
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "pr20261109b"
down_revision = "pr20261109a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("prorrogas_installments", sa.Column("receipt_path", sa.Text()))
    op.add_column("prorrogas_installments", sa.Column("receipt_uploaded_at", sa.DateTime()))


def downgrade():
    op.drop_column("prorrogas_installments", "receipt_uploaded_at")
    op.drop_column("prorrogas_installments", "receipt_path")
