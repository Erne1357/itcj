"""titulatec: promedios oficiales por numero de control

Escrita a mano (sin autogenerate), junto con `models/official_average.py`: el CI
arma el esquema con `create_all` y dev/prod con Alembic, asi que la tabla y su
CHECK se declaran AQUI y en el modelo con el mismo nombre.

Que agrega
----------
`titulatec_official_averages`: el promedio oficial (Servicios Escolares) de un
egresado por numero de control, aunque aun no tenga proceso; se copia a
`titulatec_processes.final_average` al aplicarse. Tabla nueva, sin backfill, sin
DML, sin permisos nuevos.

Downgrade (CON PERDIDA si hay promedios aun sin aplicar): borra la tabla; el
codigo viejo no la lee. Los `final_average` ya copiados a procesos se quedan.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261013b
Revises: tt20261013a
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261013b"
down_revision = "tt20261013a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_official_averages"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_table(
        _TABLE,
        sa.Column("control_number", sa.String(length=20), nullable=False),
        sa.Column("average", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("loaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("average BETWEEN 0 AND 100",
                           name="ck_titulatec_official_averages_range"),
        sa.ForeignKeyConstraint(["loaded_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("control_number"),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
