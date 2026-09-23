"""helpdesk: columna split_from_ticket_id (vinculo de "Partir ticket")

Feature "Partir ticket": un ticket puede dividirse en varios tickets hijos
independientes. `split_from_ticket_id` en el hijo apunta al `id` del ticket
padre del que se partio. Auto-referencial sobre `helpdesk_ticket`.

Nullable (la inmensa mayoria de tickets nunca se parte de otro), sin
`server_default` — no aplica, es NULL por definicion para cualquier ticket
que no sea resultado de una division. `ON DELETE SET NULL`: si el padre se
borra (caso raro, admin), los hijos no deben desaparecer ni bloquear el
borrado — simplemente pierden la referencia.

ORDEN OBLIGATORIO: esta migracion se aplica ANTES de que el modelo declare
la columna (ver `apps/helpdesk/models/ticket.py`) para que otros agentes con
tests que insertan `Ticket` en la BD de dev no truenen por una columna que
el modelo espera y la tabla todavia no tiene. Mismo patron que
`tt20260917a_titulatec_enrollment_rejection_sent.py`.

Escrita a mano (no autogenerate): el autogenerate de este repo arrastra
drift ajeno que borra indices/constraints de otras apps (agendatec,
warehouse) sin relacion con este cambio.

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(pool_mode=transaction rompe DDL).

Revision ID: hd20260922a
Revises: tt20260917a
"""
from alembic import op
import sqlalchemy as sa

revision = "hd20260922a"
down_revision = "tt20260917a"
branch_labels = None
depends_on = None

_TABLE = "helpdesk_ticket"
_COLUMN = "split_from_ticket_id"
_INDEX = "ix_helpdesk_ticket_split_from_ticket_id"
_FK = "helpdesk_ticket_split_from_ticket_id_fkey"


def upgrade():
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))
    op.create_index(_INDEX, _TABLE, [_COLUMN])
    op.create_foreign_key(_FK, _TABLE, _TABLE, [_COLUMN], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
