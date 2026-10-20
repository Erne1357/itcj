"""titulatec: indice parcial de prefijo sobre `titulatec_audit_log.subject_label`

Escrita a mano (sin autogenerate). Medido con 500 mil filas: la rama «solicitud
previa» del expediente (`?process_id=N`) y el filtro «Alumno» leian ~100 mil filas
sin `process_id` (88-208 ms); con este indice (btree `text_pattern_ops`, solo
filas con `process_id IS NULL`, ~700 kB) pasan a ~1 ms por `BitmapOr` junto con
`ix_titulatec_audit_log_process_id_occurred_at`. Sin `pg_trgm` a proposito.

El modelo `models/audit_log.py` declara el MISMO indice (el CI usa `create_all`).

Downgrade: quita el indice (no pierde datos).

Revision ID: tt20261007c
Revises: tt20261007b
Create Date: 2026-10-07
"""
from alembic import op

revision = "tt20261007c"
down_revision = "tt20261007b"
branch_labels = None
depends_on = None

_INDEX = "ix_titulatec_audit_log_subject_label_prefix"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON titulatec_audit_log "
        "(subject_label text_pattern_ops) WHERE process_id IS NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
