"""titulatec: bitacora (`titulatec_audit_log`) inmutable + backfill

Spec `2026-10-07-titulatec-bitacora-design.md` §3 y §4.1. Escrita a mano (sin
autogenerate: la deriva de modelos de otras apps borraria cosas ajenas). El CI
arma el esquema con `create_all` y dev/prod con Alembic: la tabla se declara
AQUI y en `models/audit_log.py` con los mismos nombres; el trigger llega al CI
por el listener `after_create` del modelo.

Que crea
--------
- `titulatec_audit_log` + 7 indices `ix_titulatec_audit_log_*`.
- Funcion `titulatec_audit_log_guard()` y 3 triggers (UPDATE siempre falla;
  DELETE/TRUNCATE solo con `SET LOCAL titulatec.audit_purge = 'on'`).
- Backfill: una fila `source='process_event'` por cada `titulatec_process_events`
  (marcada `payload.backfilled = true`), para que la bitacora arranque con el
  historial que ya existia.

Downgrade: quita triggers, funcion y tabla (la bitacora se pierde; el historial
de procesos sigue en `titulatec_process_events`).

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261007b
Revises: tt20261007a
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261007b"
down_revision = "tt20261007a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_audit_log"

# COPIA LITERAL de `models/audit_log.py::IMMUTABILITY_SQL` / `DROP_IMMUTABILITY_SQL`
# (no se importa: una migracion no debe cambiar si el modelo cambia despues).
IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION titulatec_audit_log_guard() RETURNS trigger AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'titulatec_audit_log es inmutable: UPDATE no permitido';
    END IF;
    IF COALESCE(current_setting('titulatec.audit_purge', true), '') = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'titulatec_audit_log es inmutable: % no permitido', TG_OP;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_update ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_update
    BEFORE UPDATE ON titulatec_audit_log
    FOR EACH ROW EXECUTE FUNCTION titulatec_audit_log_guard();

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_delete ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_delete
    BEFORE DELETE ON titulatec_audit_log
    FOR EACH ROW EXECUTE FUNCTION titulatec_audit_log_guard();

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_truncate ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_truncate
    BEFORE TRUNCATE ON titulatec_audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION titulatec_audit_log_guard();
"""

DROP_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_truncate ON titulatec_audit_log;
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_delete ON titulatec_audit_log;
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_update ON titulatec_audit_log;
DROP FUNCTION IF EXISTS titulatec_audit_log_guard();
"""

# Modulo por prefijo del event_type (spec §4.1). `library_payment_` va ANTES de
# `library_`; lo que no coincide cae en `processes`.
BACKFILL_SQL = r"""
INSERT INTO titulatec_audit_log
    (occurred_at, source, action, module, actor_id, actor_kind, process_id, reason, payload)
SELECT created_at,
       'process_event',
       'process.' || event_type,
       CASE
           WHEN event_type LIKE 'document\_%' THEN 'documents'
           WHEN event_type LIKE 'appointment\_%' THEN 'appointments'
           WHEN event_type LIKE 'library\_payment\_%' THEN 'cashier'
           WHEN event_type LIKE 'library\_%' THEN 'library'
           WHEN event_type LIKE 'survey\_%' THEN 'surveys'
           WHEN event_type LIKE 'enrollment\_%' THEN 'access'
           ELSE 'processes'
       END,
       actor_id,
       CASE WHEN actor_id IS NULL THEN 'system' ELSE 'user' END,
       process_id,
       COALESCE(payload::jsonb->>'reason', payload::jsonb->>'note'),
       CASE jsonb_typeof(payload::jsonb)
           WHEN 'object' THEN jsonb_set(payload::jsonb, '{backfilled}', 'true')::json
           WHEN 'null' THEN '{"backfilled": true}'::json
           ELSE jsonb_build_object('backfilled', true, 'value', payload::jsonb)::json
       END
  FROM titulatec_process_events
 ORDER BY id
"""


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_kind", sa.String(length=12), nullable=False),
        sa.Column("actor_label", sa.String(length=120), nullable=True),
        sa.Column("entity_type", sa.String(length=48), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("subject_label", sa.String(length=160), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("route", sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_titulatec_audit_log_occurred_at", _TABLE, ["occurred_at"])
    op.create_index("ix_titulatec_audit_log_module_occurred_at", _TABLE, ["module", "occurred_at"])
    op.create_index("ix_titulatec_audit_log_actor_id_occurred_at", _TABLE, ["actor_id", "occurred_at"])
    op.create_index("ix_titulatec_audit_log_process_id_occurred_at", _TABLE, ["process_id", "occurred_at"])
    op.create_index("ix_titulatec_audit_log_entity_type_entity_id", _TABLE, ["entity_type", "entity_id"])
    op.create_index("ix_titulatec_audit_log_request_id", _TABLE, ["request_id"])
    op.create_index("ix_titulatec_audit_log_action", _TABLE, ["action"])

    # Backfill ANTES del trigger: el INSERT no lo toca, pero asi la tabla nace
    # ya poblada y protegida en el mismo paso.
    op.execute(sa.text(BACKFILL_SQL))
    op.execute(sa.text(IMMUTABILITY_SQL))


def downgrade() -> None:
    op.execute(sa.text(DROP_IMMUTABILITY_SQL))
    op.drop_table(_TABLE)
