"""titulatec: estado awaiting_access y columnas de acceso de Centro de Computo

Modo OFICIAL, aprobar una solicitud SIN cuenta en `core_users` ya no crea el
usuario de una vez: la deja en `awaiting_access` y la manda a la bandeja de
Centro de Computo, que es quien da el NIP (`grant_access`) o la devuelve a
Servicios Escolares (`return_to_review`). Mientras espera acceso la solicitud
sigue VIVA: otra del mismo (convocatoria, numero de control) abriria un
segundo NIP o una segunda liga para la misma persona, igual que ya pasa con
`approved` (`tt20260915a`).

Cambia el predicado del indice parcial `uq_titulatec_enrollment_req_open`
(`op.execute`, Alembic no autogenera indices parciales, mismo patron que
`tt20260908a`/`tt20260915a`) y agrega 6 columnas nuevas, todas nullable:

- `access_granted_by_id` / `access_granted_at` / `access_sent_at`: las
  escribe `grant_access()` (y `approve()`/`reassign_nip()` en sus ramas sin
  liga). `access_sent_at` queda NULL si el correo con el usuario y el NIP no
  salio (mismo patron que `verify_sent_at`).
- `returned_by_id` / `returned_at` / `return_note`: las escribe
  `return_to_review()` cuando Centro de Computo regresa la solicitud a
  Servicios Escolares sin dar acceso.

El mismo predicado vive en el `__table_args__` del modelo, que es lo que usa
el `create_all` del CI: los dos los amarra
`test_el_modelo_y_la_migracion_declaran_el_mismo_predicado`.

Escrita a mano (no autogenerate): el autogenerate de este repo arrastra drift
ajeno que borra indices/constraints de otras apps (gotcha del CLAUDE.md raiz).

El upgrade solo fallaria si ya hubiera, para el mismo (convocatoria, control),
una fila 'awaiting_access' junto a otra viva: ningun escritor produce
'awaiting_access' antes de esta revision, asi que no hay filas que violen el
indice nuevo. El downgrade relaja el predicado y no puede fallar; las
columnas se quitan sin `server_default` porque nacen NULL en toda fila
existente.

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(pool_mode=transaction rompe DDL).

Revision ID: tt20260924a
Revises: hd20260922a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260924a"
down_revision = "hd20260922a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_enrollment_requests"
_INDEX = "uq_titulatec_enrollment_req_open"
_OPEN_NEW = "status IN ('unverified','verified','pending_review','approved','awaiting_access')"
_OPEN_OLD = "status IN ('unverified','verified','pending_review','approved')"


def _recreate(predicate: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} "
        f"ON {_TABLE} (cohort_id, control_number) "
        f"WHERE {predicate}"
    )


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("access_granted_by_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("access_granted_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column("access_sent_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column("returned_by_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("returned_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column("return_note", sa.Text(), nullable=True))

    op.create_foreign_key(
        "titulatec_enrollment_requests_access_granted_by_id_fkey",
        _TABLE, "core_users", ["access_granted_by_id"], ["id"],
    )
    op.create_foreign_key(
        "titulatec_enrollment_requests_returned_by_id_fkey",
        _TABLE, "core_users", ["returned_by_id"], ["id"],
    )

    _recreate(_OPEN_NEW)


def downgrade() -> None:
    _recreate(_OPEN_OLD)

    op.drop_constraint(
        "titulatec_enrollment_requests_returned_by_id_fkey", _TABLE, type_="foreignkey")
    op.drop_constraint(
        "titulatec_enrollment_requests_access_granted_by_id_fkey", _TABLE, type_="foreignkey")

    op.drop_column(_TABLE, "return_note")
    op.drop_column(_TABLE, "returned_at")
    op.drop_column(_TABLE, "returned_by_id")
    op.drop_column(_TABLE, "access_sent_at")
    op.drop_column(_TABLE, "access_granted_at")
    op.drop_column(_TABLE, "access_granted_by_id")
