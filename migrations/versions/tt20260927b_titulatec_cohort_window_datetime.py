"""titulatec: la ventana de la convocatoria gana hora y pasa a NOT NULL

`titulatec_cohorts.opens_at` y `closes_at`: `DATE` nullable -> `TIMESTAMP`
(naive, hora local de APP_TZ: el mismo reloj que `db_now()` y que `NOW()` de
Postgres) NOT NULL. Spec `2026-09-27-titulatec-sii-informa-se-decide-design.md`
§B1 / D9.

La conversion NO mueve ninguna ventana:
  - apertura D -> D 00:00 (`opens_at::timestamp`);
  - cierre   D -> D 23:59:59 (`closes_at::timestamp + interval '23:59:59'`),
    que la UI muestra «23:59»: quien envia a las 23:59:30 del ultimo dia sigue
    dentro, igual que con la columna de fecha.

Antes de convertir:
  - apertura vacia -> fecha de creacion 00:00 (`created_at::date`): equivale a
    «abierta desde siempre», que es lo que significaba el NULL;
  - cierre vacio -> la migracion ABORTA, antes de cualquier DDL, nombrando cada
    convocatoria (`id` y `name`). No se inventa un cierre: se configura desde
    el panel y se vuelve a correr.

Downgrade: `TIMESTAMP` -> `DATE` (`::date`, se pierde la hora) y nullable otra
vez.

Escrita a mano (no autogenerate: arrastra drift ajeno). Correr con
MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer. Postgres corre
el DDL dentro de la transaccion de Alembic, asi que un aborto no deja nada a
medias.

Revision ID: tt20260927b
Revises: tt20260927a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260927b"
down_revision = "tt20260927a"
branch_labels = None
depends_on = None

_COHORTS = "titulatec_cohorts"


def _cohorts_without_close(conn) -> list[tuple[int, str]]:
    """`(id, name)` de cada convocatoria sin fecha de cierre, por `id`."""
    rows = conn.execute(sa.text(
        f"SELECT id, name FROM {_COHORTS} WHERE closes_at IS NULL ORDER BY id"
    )).fetchall()
    return [(r[0], r[1]) for r in rows]


def _abort_message(rows) -> str:
    """El texto del aborto: QUE convocatorias y DONDE se arreglan."""
    lista = ", ".join(f"id={cid} «{name}»" for cid, name in rows)
    return (
        f"tt20260927b: {len(rows)} convocatoria(s) sin fecha de cierre: {lista}. "
        "El cierre pasa a ser obligatorio y la migración no lo inventa. "
        "Configura la fecha de cierre en Convocatorias › Resumen › Ventana de "
        "inscripción y vuelve a correr la migración."
    )


def upgrade() -> None:
    rows = _cohorts_without_close(op.get_bind())
    if rows:
        raise RuntimeError(_abort_message(rows))

    op.execute(
        f"UPDATE {_COHORTS} SET opens_at = created_at::date WHERE opens_at IS NULL"
    )
    op.alter_column(
        _COHORTS, "opens_at",
        existing_type=sa.Date(), type_=sa.DateTime(), existing_nullable=True,
        postgresql_using="opens_at::timestamp",
    )
    op.alter_column(
        _COHORTS, "closes_at",
        existing_type=sa.Date(), type_=sa.DateTime(), existing_nullable=True,
        postgresql_using="closes_at::timestamp + interval '23:59:59'",
    )
    op.alter_column(_COHORTS, "opens_at", existing_type=sa.DateTime(), nullable=False)
    op.alter_column(_COHORTS, "closes_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    op.alter_column(_COHORTS, "closes_at", existing_type=sa.DateTime(), nullable=True)
    op.alter_column(_COHORTS, "opens_at", existing_type=sa.DateTime(), nullable=True)
    op.alter_column(
        _COHORTS, "closes_at",
        existing_type=sa.DateTime(), type_=sa.Date(), existing_nullable=True,
        postgresql_using="closes_at::date",
    )
    op.alter_column(
        _COHORTS, "opens_at",
        existing_type=sa.DateTime(), type_=sa.Date(), existing_nullable=True,
        postgresql_using="opens_at::date",
    )
