"""titulatec: capacidad total de espacios sin horario (walkin)

La migración convierte `capacity` de espacios `walkin` de «por franja» a «total
del espacio» (spec 2026-09-29 §3.2, D3, §7.2). Solo de datos: sin cambio de
esquema. El tope 500 es el del editor (`ReviewWindowService`) y de `add_places`
(regla de diseño, evita que un espacio se quede sin poder guardar).

- `capacity = LEAST(500, GREATEST(1, franjas × capacity))`
- `franjas = FLOOR((end_time - start_time) / 60 / slot_minutes)::int`
- Solo `visibility='walkin'`; `bookable` y `private` no cambian.

Downgrade: inversa aproximada (`capacity / franjas`), documentada como tal.
Nunca deja `capacity < 1` (CHECK de la columna); como cada franja tenía ≤
`capacity` citas, el total nuevo ≥ citas vivas: nadie queda excedido.

Se prueba en dev: ventana walkin de legado con citas vivas a varias horas →
upgrade → ocupación y tablero correctos → downgrade → upgrade.

Revisión ID: tt20260929a
Revises: tt20260928a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260929a"
down_revision = "tt20260928a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_review_windows"

# SQL de upgrade: capacity = LEAST(500, GREATEST(1, franjas × capacity))
UPGRADE_SQL = f"""
UPDATE {_TABLE}
SET capacity = LEAST(
    500,
    GREATEST(
        1,
        FLOOR(EXTRACT(EPOCH FROM (end_time - start_time)) / 60 / slot_minutes)::int * capacity
    )
)
WHERE visibility = 'walkin'
"""

# SQL de downgrade: inversa aproximada capacity / NULLIF(franjas, 0)
DOWNGRADE_SQL = f"""
UPDATE {_TABLE}
SET capacity = GREATEST(
    1,
    FLOOR(capacity / NULLIF(FLOOR(EXTRACT(EPOCH FROM (end_time - start_time)) / 60 / slot_minutes)::int, 0))::int
)
WHERE visibility = 'walkin'
"""


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
