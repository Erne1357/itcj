"""prorrogas_tec: parcialidades de hasta 6 (historico del Excel)

Escrita a mano, junto con `models/plan.py`: el CI arma el esquema con `create_all`
y dev/prod con Alembic, asi que el CHECK se declara AQUI y en el modelo con el
mismo nombre.

Que hace
--------
El historico del Excel trae prorrogas de hasta 6 pagos. Reemplaza el CHECK
`ck_prorrogas_installments_number` de `number BETWEEN 1 AND 3` a `1 AND 6`.
El tope de 3 para planes nuevos de la app lo sigue poniendo `MAX_PAGOS` en el servicio.

Downgrade
---------
Regresa el CHECK a `1 AND 3` (falla si ya hay parcialidades 4 a 6).

Revision ID: pr20261101a
Revises: pr20261031a
Create Date: 2026-11-01
"""
from alembic import op

revision = "pr20261101a"
down_revision = "pr20261031a"
branch_labels = None
depends_on = None

_CK = "ck_prorrogas_installments_number"


def upgrade():
    op.drop_constraint(_CK, "prorrogas_installments", type_="check")
    op.create_check_constraint(_CK, "prorrogas_installments", "number BETWEEN 1 AND 6")


def downgrade():
    op.drop_constraint(_CK, "prorrogas_installments", type_="check")
    op.create_check_constraint(_CK, "prorrogas_installments", "number BETWEEN 1 AND 3")
