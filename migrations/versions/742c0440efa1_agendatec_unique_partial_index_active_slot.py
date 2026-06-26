"""agendatec: unique partial index on slot_id for active appointments

Revision ID: 742c0440efa1
Revises: e8368b899ed1
Create Date: 2026-06-19

ADVERTENCIA DE SEGURIDAD DE DATOS
-----------------------------------
Este índice único parcial cubre únicamente las filas cuyo status es
'SCHEDULED' o 'DONE' — los dos estados que consideran al slot como
ocupado/consumado.

Si en la base de datos existen DOS O MÁS filas en agendatec_appointments
con el mismo slot_id y un status dentro de ese rango, PostgreSQL RECHAZARÁ
la creación del índice con un error de unicidad.

Eso indicaría DATOS CORRUPTOS (doble-booking que ya llegó a la BD a pesar
del compare-and-set en código). Antes de aplicar esta migración, ejecutar:

    SELECT slot_id, COUNT(*) AS cnt
    FROM agendatec_appointments
    WHERE status IN ('SCHEDULED', 'DONE')
    GROUP BY slot_id
    HAVING COUNT(*) > 1;

Si esa consulta devuelve filas, limpiar la corrupción primero y LUEGO
aplicar la migración.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '742c0440efa1'
down_revision = 'e8368b899ed1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Índice único parcial: garantiza que ningún slot tenga más de una cita
    # activa (SCHEDULED) o consumada (DONE) al mismo tiempo.
    # NO_SHOW y CANCELED quedan fuera del índice — un slot liberado por
    # cancelación puede volver a ser tomado.
    op.create_index(
        'uq_agendatec_appointments_active_slot',
        'agendatec_appointments',
        ['slot_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('SCHEDULED', 'DONE')"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_agendatec_appointments_active_slot',
        table_name='agendatec_appointments',
    )
