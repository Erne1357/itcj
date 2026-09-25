"""titulatec: consultas de elegibilidad SII y aprobacion automatica por convocatoria

Tabla nueva `titulatec_eligibility_checks`: una fila por INTENTO de consulta
contra el SII (`EligibilityService.check`, Tarea 4). `status` nace en
'pending' -- la fila se abre al empezar a consultar y se cierra con
`finished_at`/`duration_ms` al terminar (o con `error` si el SII no
responde). El NIP del SII NUNCA vive aqui: ni en `facts` ni en `results`
(spec `2026-09-25-titulatec-elegibilidad-sii-design.md` §3.2, §5).

Dos columnas nuevas, ambas fuera de cualquier flujo existente (no requieren
backfill de datos que ya haya escritores produciendo):
- `titulatec_enrollment_requests.last_check_id`: la consulta VIGENTE de la
  solicitud. Nullable -- ninguna solicitud existente tiene una.
- `titulatec_cohorts.sii_auto_approve`: interruptor de aprobacion
  automatica (spec S8). NOT NULL con `server_default TRUE` porque hay
  convocatorias existentes: nacen con la automatizacion encendida, que es lo
  que ya pasa hoy en el modo `school_services`/`computer_center` (SE sigue
  aprobando a mano) -- el interruptor solo importa cuando
  `TITULATEC_ENROLLMENT_REVIEWER=sii`.

Orden: `titulatec_eligibility_checks` se crea PRIMERO porque
`last_check_id` la referencia. Escrita a mano (no autogenerate): el
autogenerate de este repo arrastra drift ajeno que borra indices/constraints
de otras apps (gotcha del CLAUDE.md raiz).

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(pool_mode=transaction rompe DDL).

Revision ID: tt20260925a
Revises: tt20260924a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260925a"
down_revision = "tt20260924a"
branch_labels = None
depends_on = None

_CHECKS = "titulatec_eligibility_checks"
_REQUESTS = "titulatec_enrollment_requests"
_COHORTS = "titulatec_cohorts"


def upgrade() -> None:
    op.create_table(
        _CHECKS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("rules_version", sa.String(40), nullable=True),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("identity_mismatch", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["request_id"], [f"{_REQUESTS}.id"]),
    )
    op.create_index(
        f"ix_{_CHECKS}_request_id", _CHECKS, ["request_id"],
    )
    op.create_index(
        f"ix_{_CHECKS}_request_status", _CHECKS, ["request_id", "status"],
    )

    op.add_column(_REQUESTS, sa.Column("last_check_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        f"{_REQUESTS}_last_check_id_fkey",
        _REQUESTS, _CHECKS, ["last_check_id"], ["id"],
    )

    op.add_column(
        _COHORTS,
        sa.Column("sii_auto_approve", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column(_COHORTS, "sii_auto_approve")

    op.drop_constraint(f"{_REQUESTS}_last_check_id_fkey", _REQUESTS, type_="foreignkey")
    op.drop_column(_REQUESTS, "last_check_id")

    op.drop_index(f"ix_{_CHECKS}_request_status", table_name=_CHECKS)
    op.drop_index(f"ix_{_CHECKS}_request_id", table_name=_CHECKS)
    op.drop_table(_CHECKS)
