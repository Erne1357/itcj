"""titulatec: observacion CON ADEUDO del no adeudo de biblioteca

Spec `2026-10-07-titulatec-liberados-biblioteca-helpdesk-design.md` §2
(D3/D4). Escrita a mano (sin autogenerate: la deriva de modelos de otras apps
borraria cosas que no son de esta entrega), junto con
`models/library_clearance.py`: el CI arma el esquema con `create_all` y
dev/prod con Alembic, asi que la columna se declara AQUI y en el modelo con el
mismo nombre y tipo.

Que agrega
----------
`titulatec_library_clearances.observation_kind` String(20) NULL: el TIPO de la
observacion vigente de Biblioteca. Dominio (sin CHECK, como todos los
«enums» de la app): `blocking` (la de siempre: detiene todo, incluido el
pago, D4) | `with_debt` (con adeudo: Caja cobra, el pago queda retenido hasta
que Biblioteca activa, D3). NULL fuera de `status='observed'`.

Backfill: toda fila `observed` que ya existia era la observacion de siempre,
asi que recibe `blocking` (el codigo nuevo lee NULL dentro de `observed`
tambien como `blocking`; el UPDATE deja el dato explicito).

Downgrade (CON PERDIDA, documentada)
-------------------------------------
Quita la columna. El codigo viejo trata TODA fila `observed` como la
observacion de siempre (sin pago posible). Una `with_debt` CON pago retenido
conserva `paid_at`/`paid_by_id`/`receipt_number` en la fila, pero el codigo
viejo no los mira: si Biblioteca la activa con el codigo viejo, regresa a
«Por revisar» y Caja podria cobrarla OTRA VEZ. Antes de bajar, listarlas y
resolverlas a mano (activarlas con el codigo nuevo, o revertir su pago):

    SELECT id, process_id, total_amount, paid_at, receipt_number
      FROM titulatec_library_clearances
     WHERE status = 'observed' AND observation_kind = 'with_debt'
       AND paid_at IS NOT NULL;

Las `with_debt` sin pago bajan como observacion normal (siguen detenidas;
Biblioteca las activa y las registra de nuevo). El tipo queda en el payload
del evento `library_observed` (`kind`).

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261007a
Revises: tt20261006a
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261007a"
down_revision = "tt20261006a"
branch_labels = None
depends_on = None


BACKFILL_BLOCKING_SQL = """
UPDATE titulatec_library_clearances
   SET observation_kind = 'blocking'
 WHERE status = 'observed' AND observation_kind IS NULL
"""


def upgrade() -> None:
    op.add_column("titulatec_library_clearances",
                  sa.Column("observation_kind", sa.String(length=20), nullable=True))
    op.execute(sa.text(BACKFILL_BLOCKING_SQL))


def downgrade() -> None:
    op.drop_column("titulatec_library_clearances", "observation_kind")
