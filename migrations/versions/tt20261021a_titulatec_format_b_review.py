"""titulatec fase 3: columnas de revision/FIFO del Formato B

Escrita a mano (sin autogenerate: arrastra deriva de otras apps), junto con
`models/format_b.py`: el CI arma el esquema con `create_all` y dev/prod con
Alembic, asi que las columnas se declaran AQUI y en el modelo con el mismo
nombre y tipo.

Spec: docs/superpowers/specs/2026-10-21-titulatec-fase3-formato-b-titulacion-design.md

Que agrega a `titulatec_format_b`
---------------------------------
- `submitted_at` DateTime NULL: ultimo envio; ancla del FIFO de la bandeja.
- `submission_count` Integer NOT NULL DEFAULT 0: cuantas veces se envio.
- `review_observations` JSON NULL: observaciones por seccion/campo.
- `reviewed_by_id` BigInteger FK core_users NULL y `reviewed_at` DateTime NULL.
- `modality_id` Integer FK titulatec_modalities NULL.
- indice `ix_titulatec_format_b_status_submitted (status, submitted_at)`.

Backfill (datos)
----------------
`submitted_at` de los Formatos B que ya salieron de `draft`: la fecha mas
reciente de la bitacora con `action = 'format_b.submitted'` del mismo proceso;
si no hay, el `created_at` del propio Formato B. Los `draft` quedan NULL.
`BACKFILL_SQL` es constante del modulo para poder ejecutarla en pruebas.

Downgrade (CON PERDIDA): quita las columnas y el indice; se pierden las
observaciones, el revisor y el contador de envios.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261021a
Revises: d1r3ct0ry03
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261021a"
down_revision = "d1r3ct0ry03"
branch_labels = None
depends_on = None

_TABLE = "titulatec_format_b"
_INDEX = "ix_titulatec_format_b_status_submitted"

BACKFILL_SQL = """
UPDATE titulatec_format_b AS fb
   SET submitted_at = COALESCE(
        (SELECT MAX(a.occurred_at)
           FROM titulatec_audit_log AS a
          WHERE a.action = 'format_b.submitted'
            AND a.process_id = fb.process_id),
        fb.created_at)
 WHERE fb.status <> 'draft'
   AND fb.submitted_at IS NULL
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(_TABLE, sa.Column("submitted_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column(
        "submission_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column(_TABLE, sa.Column("review_observations", sa.JSON(), nullable=True))
    op.add_column(_TABLE, sa.Column("reviewed_by_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column("modality_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "titulatec_format_b_reviewed_by_id_fkey", _TABLE, "core_users",
        ["reviewed_by_id"], ["id"])
    op.create_foreign_key(
        "titulatec_format_b_modality_id_fkey", _TABLE, "titulatec_modalities",
        ["modality_id"], ["id"])
    op.create_index(_INDEX, _TABLE, ["status", "submitted_at"])
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint("titulatec_format_b_modality_id_fkey", _TABLE, type_="foreignkey")
    op.drop_constraint("titulatec_format_b_reviewed_by_id_fkey", _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "modality_id")
    op.drop_column(_TABLE, "reviewed_at")
    op.drop_column(_TABLE, "reviewed_by_id")
    op.drop_column(_TABLE, "review_observations")
    op.drop_column(_TABLE, "submission_count")
    op.drop_column(_TABLE, "submitted_at")
