"""titulatec: tabla cifrada de NIPs precargados del SII

Escrita a mano (sin autogenerate), junto con `models/nip_stash.py`: el CI arma
el esquema con `create_all` y dev/prod con Alembic, asi que la tabla se declara
AQUI y en el modelo con las mismas columnas y tipos.

Que agrega
----------
`titulatec_nip_stash`: un NIP cifrado (Fernet) por numero de control, cargado por
Servicios Escolares y consumido (borrado) al aprobar o al cerrar la
convocatoria. Tabla nueva, sin backfill, sin DML, sin permisos nuevos.

Downgrade (CON PERDIDA si hay NIPs precargados): borra la tabla; el codigo viejo
no la lee.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261013a
Revises: tt20261012a
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261013a"
down_revision = "tt20261012a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_nip_stash"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_table(
        _TABLE,
        sa.Column("control_number", sa.String(length=20), nullable=False),
        sa.Column("nip_cipher", sa.Text(), nullable=False),
        sa.Column("loaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["loaded_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("control_number"),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
