"""titulatec: bandeja de salida de correos del proceso al egresado

Tabla nueva `titulatec_email_outbox` (spec
`2026-09-28-titulatec-correos-notificaciones-design.md` §6, D4 -- "enfoque
A"): una fila por correo pendiente o ya enviado, escrita en la MISMA
transaccion del evento que la origina (dictamen de documentos, avance/
rechazo de fase, resultado de GTV, cita de cotejo, sus tres recordatorios).
La tarea periodica `titulatec.email_dispatch` (Celery, cada minuto, `FOR
UPDATE SKIP LOCKED`) es quien la despacha; esta migracion solo crea la
tabla -- el service de encolado y el despachador son tareas aparte.

Cinco nombres de indice/constraint, elegidos para el despachador y los
recordatorios:
- `uq_titulatec_email_outbox_dedupe_key`: UNIQUE sobre `dedupe_key`
  (nullable). Solo los tres recordatorios la usan; el resto de los `kind`
  la dejan NULL -- Postgres admite multiples NULL bajo un UNIQUE normal,
  asi que no chocan entre si. Un `INSERT ... ON CONFLICT (dedupe_key) DO
  NOTHING` hace que el barrido diario, corrido dos veces, no duplique.
- `ix_titulatec_email_outbox_status_not_before`: compuesto sobre
  `(status, not_before)`, la llave con la que el despachador toma su lote
  de filas `pending` listas (`not_before <= ahora`).
- `ix_titulatec_email_outbox_process_id` / `_user_id` / `_group_key`:
  lookups del expediente (bitacora por proceso), del despachador
  (agrupado por `group_key`) y de cualquier consulta por destinatario.

Este archivo y el modelo (`itcj2/apps/titulatec/models/email_outbox.py`)
declaran los 5 nombres de forma IDENTICA a proposito: el CI arma el
esquema de test con `create_all` (sin Alembic) y dev/prod lo arman con
esta migracion -- si los nombres divergieran, una base tendria un indice
que la otra no.

Escrita a mano (no autogenerate: arrastra drift ajeno que borra el candado
anti doble-booking de agendatec y UNIQUE de helpdesk -- gotcha del
CLAUDE.md raiz). Solo `CREATE TABLE` + indices, no toca ninguna fila
existente. Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca
contra PgBouncer (`pool_mode=transaction` rompe DDL).

Revision ID: tt20260928a
Revises: tt20260927b
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260928a"
down_revision = "tt20260927b"
branch_labels = None
depends_on = None

_TABLE = "titulatec_email_outbox"
_PROCESSES = "titulatec_processes"
_USERS = "core_users"


def upgrade() -> None:
    # Tabla nueva, sin filas existentes que puedan tener un lock largo --
    # el tope es red de seguridad (mismo razonamiento que tt20260927a): si
    # algo ajeno tiene un lock sobre estas tablas, el deploy aborta limpio
    # en vez de colgarse sin tope.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_key", sa.String(length=80), nullable=True),
        sa.Column("dedupe_key", sa.String(length=160), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20),
                  server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(),
                  server_default=sa.text("0"), nullable=False),
        sa.Column("not_before", sa.DateTime(),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("sent_to", sa.String(length=150), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["process_id"], [f"{_PROCESSES}.id"]),
        sa.ForeignKeyConstraint(["user_id"], [f"{_USERS}.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_titulatec_email_outbox_dedupe_key"),
    )
    op.create_index(
        "ix_titulatec_email_outbox_process_id", _TABLE, ["process_id"],
    )
    op.create_index(
        "ix_titulatec_email_outbox_user_id", _TABLE, ["user_id"],
    )
    op.create_index(
        "ix_titulatec_email_outbox_group_key", _TABLE, ["group_key"],
    )
    op.create_index(
        "ix_titulatec_email_outbox_status_not_before", _TABLE,
        ["status", "not_before"],
    )


def downgrade() -> None:
    op.drop_index("ix_titulatec_email_outbox_status_not_before", table_name=_TABLE)
    op.drop_index("ix_titulatec_email_outbox_group_key", table_name=_TABLE)
    op.drop_index("ix_titulatec_email_outbox_user_id", table_name=_TABLE)
    op.drop_index("ix_titulatec_email_outbox_process_id", table_name=_TABLE)
    op.drop_table(_TABLE)
