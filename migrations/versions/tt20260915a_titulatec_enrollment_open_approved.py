"""titulatec: el indice de solicitud viva incluye 'approved'

Toda solicitud de auto-inscripcion pasa ahora por la bandeja de Servicios
Escolares. Aprobar la de una cuenta que ya existe la deja en 'approved' mientras
la liga de activacion viaja al correo del solicitante, y durante ese tiempo la
solicitud sigue VIVA: otra del mismo numero de control en la misma convocatoria
abriria una segunda liga (o un NIP) para la misma persona.

Solo cambia el predicado del indice parcial `uq_titulatec_enrollment_req_open`.
Alembic no autogenera indices parciales, asi que va con `op.execute`, igual que
en `tt20260908a`. El mismo predicado vive en el `__table_args__` del modelo, que
es lo que usa el `create_all` del CI.

El upgrade solo fallaria si ya hubiera, para el mismo (convocatoria, control),
una fila 'approved' junto a otra viva: ningun escritor producia 'approved' antes
de esta revision. El downgrade relaja el predicado y no puede fallar.

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(gotcha 1).

Revision ID: tt20260915a
Revises: tt20260908a
"""
from alembic import op

revision = "tt20260915a"
down_revision = "tt20260908a"
branch_labels = None
depends_on = None

_INDEX = "uq_titulatec_enrollment_req_open"
_OPEN_NEW = "status IN ('unverified','verified','pending_review','approved')"
_OPEN_OLD = "status IN ('unverified','verified','pending_review')"


def _recreate(predicate: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} "
        "ON titulatec_enrollment_requests (cohort_id, control_number) "
        f"WHERE {predicate}"
    )


def upgrade():
    _recreate(_OPEN_NEW)


def downgrade():
    _recreate(_OPEN_OLD)
