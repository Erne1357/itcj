"""titulatec: capacidad total de espacios sin horario (walkin)

La migración convierte `capacity` de espacios `walkin` de «por franja» a
«total del espacio» (spec 2026-09-29-titulatec-cotejo-espacios-design.md
§3.2, D3, D12, §7.2). Solo de datos: sin cambio de esquema.

Decisión del usuario 2026-09-29 («no creo que se puedan atender 500»): TODOS
los `walkin` existentes quedan en **30**, el mismo default con el que nace un
espacio nuevo desde este deploy (`WALKIN_CUPO_DEFAULT`,
`services/review_window_service.py`). El `GREATEST(30, vivas)` es SOLO una
red de seguridad: si un espacio ya tiene más de 30 citas VIVAS (`status NOT
IN ('cancelled', 'superseded')`), se conserva ese número de vivas para que
nadie quede excedido -nunca por debajo de lo que el egresado ya tiene
apartado-. El techo del editor y de `add_places` («Abrir más lugares») baja
de 500 a 100 (`WALKIN_TOPE`); esta migración no lo aplica a propósito: la red
de seguridad puede dejar, en casos raros, un espacio por encima de 100 -señal
de que ese encargado necesita más de un espacio, no un tope que le pierda
gente-.

- `capacity = GREATEST(30, vivas)`
- `vivas = count(*)` de `titulatec_review_appointments` de esa ventana con
  `status NOT IN ('cancelled', 'superseded')` (mismo filtro por ESTADO que
  `SlotService.occupancy`, nunca por `is_current`: un intento re-agendado
  sigue vivo aunque ya no sea el vigente).
- Solo `visibility='walkin'`; `bookable` y `private` no cambian.

Downgrade: inversa aproximada (`capacity / franjas`), documentada como tal.
Nunca deja `capacity < 1` (CHECK de la columna); como el upgrade nunca baja
`capacity` por debajo de las citas vivas, el downgrade parte de un número que
sigue siendo válido.

Se prueba en dev: ventana walkin de legado con citas vivas a varias horas →
upgrade → ocupación y tablero correctos → downgrade → upgrade.

ADVERTENCIA: No ejecutar este SQL a mano. Solo vía `alembic upgrade head` o
`alembic downgrade`. El downgrade es aproximado y puede dejar datos
inconsistentes si se aplica fuera del orden correcto de migraciones.

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
_APPTS = "titulatec_review_appointments"

# SQL de upgrade: capacity = GREATEST(30, vivas). El 30 es el default nuevo
# de un walkin (D12); el GREATEST con las vivas es la red de seguridad.
UPGRADE_SQL = f"""
UPDATE {_TABLE} w
SET capacity = GREATEST(
    30,
    (SELECT count(*) FROM {_APPTS} a
     WHERE a.window_id = w.id
       AND a.status NOT IN ('cancelled', 'superseded'))
)
WHERE w.visibility = 'walkin'
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
