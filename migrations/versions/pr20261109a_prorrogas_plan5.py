"""prorrogas_tec: esquema del Plan 5 (una solicitud por semestre, referencia, cierre y recordatorios)

Escrita a mano, junto con los modelos: el CI arma el esquema con `create_all`
y dev/prod con Alembic, asi que los nombres se declaran AQUI y en el modelo.

Que hace
--------
- Indice `uq_prorrogas_requests_abierta` (una abierta por alumno y semestre) se
  sustituye por `uq_prorrogas_requests_semestre` (una sola, aunque se rechace o cancele).
- El CHECK `ck_prorrogas_requests_status` suma el estado `cerrada_sin_plan`.
- Columnas nuevas: `prorrogas_requests.reference_path`, `.reference_uploaded_at`
  y `prorrogas_installments.last_reminder_days`.

Downgrade
---------
Inverso. Falla si hay filas `cerrada_sin_plan` o dos solicitudes de un alumno
en un mismo semestre.

Revision ID: pr20261109a
Revises: pr20261108a
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "pr20261109a"
down_revision = "pr20261108a"
branch_labels = None
depends_on = None

_CK = "ck_prorrogas_requests_status"
_VIEJO = "uq_prorrogas_requests_abierta"
_NUEVO = "uq_prorrogas_requests_semestre"


def upgrade():
    op.drop_index(_VIEJO, table_name="prorrogas_requests")
    op.create_index(_NUEVO, "prorrogas_requests", ["student_id", "period_id"], unique=True,
                    postgresql_where=sa.text("origin = 'app'"))
    op.drop_constraint(_CK, "prorrogas_requests", type_="check")
    op.create_check_constraint(
        _CK, "prorrogas_requests", "status IN ('pendiente','aceptada','rechazada','cancelada','cerrada_sin_plan')")
    op.add_column("prorrogas_requests", sa.Column("reference_path", sa.Text()))
    op.add_column("prorrogas_requests", sa.Column("reference_uploaded_at", sa.DateTime()))
    op.add_column("prorrogas_installments", sa.Column("last_reminder_days", sa.SmallInteger()))


def downgrade():
    op.drop_column("prorrogas_installments", "last_reminder_days")
    op.drop_column("prorrogas_requests", "reference_uploaded_at")
    op.drop_column("prorrogas_requests", "reference_path")
    op.drop_constraint(_CK, "prorrogas_requests", type_="check")
    op.create_check_constraint(_CK, "prorrogas_requests", "status IN ('pendiente','aceptada','rechazada','cancelada')")
    op.drop_index(_NUEVO, table_name="prorrogas_requests")
    op.create_index(_VIEJO, "prorrogas_requests", ["student_id", "period_id"], unique=True,
                    postgresql_where=sa.text("status IN ('pendiente','aceptada') AND origin = 'app'"))
