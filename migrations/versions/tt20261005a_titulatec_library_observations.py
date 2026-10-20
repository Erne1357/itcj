"""titulatec: no adeudo de biblioteca «Con observaciones»

Spec `2026-10-05-titulatec-biblioteca-observaciones-design.md` §3.1. Escrita a
mano (sin autogenerate), junto con `models/library_clearance.py`: el CI arma
el esquema con `create_all` (sin Alembic) y dev/prod con Alembic -- las
columnas de abajo estan declaradas AQUI y en el modelo, con el mismo nombre y
tipo.

Que agrega
----------
`titulatec_library_clearances` gana tres columnas NULL, la observacion
VIGENTE de Biblioteca (el historial vive en `ProcessEvent`
`library_observed`/`library_reenabled`):

* `observation_reason` Text
* `observed_by_id` BigInteger FK `core_users.id` (nombre de FK por omision
  de Postgres, igual que `library_by_id`/`paid_by_id`, para coincidir con
  `create_all`)
* `observed_at` DateTime

`status` gana el valor `observed`: es String(20) SIN CHECK de dominio, asi
que no hay restriccion que cambiar. Sin backfill (ninguna fila nace
observada).

Downgrade (CON PERDIDA, documentada)
-------------------------------------
El codigo viejo no conoce `observed`: antes de borrar las columnas, las filas
`observed` regresan a `pending` («Por revisar»), con sus montos (si los
tenian) intactos -- igual que «Rehabilitar». El motivo de la observacion se
pierde de la fila pero queda en el payload de su `ProcessEvent`.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261005a
Revises: tt20261001a
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261005a"
down_revision = "tt20261001a"
branch_labels = None
depends_on = None


DOWNGRADE_OBSERVED_TO_PENDING_SQL = """
UPDATE titulatec_library_clearances
   SET status = 'pending', updated_at = NOW()
 WHERE status = 'observed'
"""


def upgrade() -> None:
    op.add_column("titulatec_library_clearances",
                  sa.Column("observation_reason", sa.Text(), nullable=True))
    op.add_column("titulatec_library_clearances",
                  sa.Column("observed_by_id", sa.BigInteger(),
                            sa.ForeignKey("core_users.id"), nullable=True))
    op.add_column("titulatec_library_clearances",
                  sa.Column("observed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_OBSERVED_TO_PENDING_SQL))
    # DROP COLUMN se lleva la FK de `observed_by_id` con ella.
    op.drop_column("titulatec_library_clearances", "observed_at")
    op.drop_column("titulatec_library_clearances", "observed_by_id")
    op.drop_column("titulatec_library_clearances", "observation_reason")
