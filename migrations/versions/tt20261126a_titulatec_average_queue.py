"""titulatec: bandeja «Promedios» (quién y cuándo pasó un promedio a Escolares)

Escrita a mano (sin autogenerate: la deriva de modelos de otras apps borraria
cosas que no son de esta entrega), junto con `models/process.py`: el CI arma el
esquema con `create_all` y dev/prod con Alembic, asi que las columnas se declaran
AQUI y en el modelo con el mismo nombre y tipo. La FK va sin nombre explicito
(toma el de Postgres, `titulatec_processes_average_requested_by_id_fkey`, igual
en `create_all` y aqui).

Spec: docs/superpowers/specs/2026-11-26-titulatec-promedios-pendientes-design.md §3.

Que agrega
----------
`titulatec_processes.average_requested_at` DateTime NULL: cuando Centro de
Computo marco «No lo tengo» y paso el expediente a Servicios Escolares.
`titulatec_processes.average_requested_by_id` BigInteger NULL, FK a
`core_users.id` ON DELETE SET NULL: quien lo paso.

Estado derivado, sin enum: sin promedio y `average_requested_at` NULL = por
capturar en CC; sin promedio y no NULL = con Escolares; con promedio = resuelto
(las columnas se quedan como historia). Nacen NULL para todos, sin backfill: el
codigo viejo las ignora.

Downgrade (CON PERDIDA)
-----------------------
Quita las dos columnas (y con ellas la FK): los pasados a Escolares vuelven a
«Por capturar». El promedio capturado NO se pierde (vive en `final_average`).

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261126a
Revises: cam20261118a
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261126a"
down_revision = "cam20261118a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_processes"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(_TABLE, sa.Column("average_requested_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column(
        "average_requested_by_id", sa.BigInteger(),
        sa.ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "average_requested_by_id")
    op.drop_column(_TABLE, "average_requested_at")
