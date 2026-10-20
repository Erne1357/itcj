"""titulatec: la consulta al SII distingue el error que se reintenta

`titulatec_eligibility_checks.retryable` (Boolean, nullable): en una fila
`status = 'error'`, True si el SII no respondio (`SiiUnavailable`: conexion,
timeout, backend apagado) y False si el error es de configuracion (reglas
rotas, consulta invalida en el SII, falla inesperada). NULL en los demas
estados. La tarea de celery (backoff) y el barrido periodico reintentan SOLO
los `retryable` (spec `2026-09-25-titulatec-elegibilidad-sii-design.md`
§3.4: «reintentos con backoff ante `SiiUnavailable`», «errores
reintentables»); los de configuracion quedan como «Error» para Servicios
Escolares, que los reconsulta a mano cuando se corrigen.

Nullable y sin backfill: las filas `error` que ya existan quedan en NULL y el
barrido no las reintenta (el modo `sii` todavia no corre en ningun entorno).

Escrita a mano (no autogenerate: arrastra drift ajeno). Correr con
MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer.

Revision ID: tt20260925b
Revises: tt20260925a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260925b"
down_revision = "tt20260925a"
branch_labels = None
depends_on = None

_CHECKS = "titulatec_eligibility_checks"


def upgrade() -> None:
    op.add_column(_CHECKS, sa.Column("retryable", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column(_CHECKS, "retryable")
