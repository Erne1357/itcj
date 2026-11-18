"""cameras: DVRs con credenciales cifradas, sus departamentos y bitacora inmutable

Escrita a mano (sin autogenerate: el drift de Alembic borra cosas ajenas), junto
con `apps/cameras/models/`. Tablas nuevas, sin backfill. Permisos y roles van por
DML (`database/DML/cameras/`), nunca aqui.

Downgrade (CON PERDIDA si hay DVRs/bitacora): borra triggers, funcion y tablas.

Revision ID: cam20261113a
Revises: mg20261113a
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "cam20261113a"
down_revision = "mg20261113a"
branch_labels = None
depends_on = None

# Copia literal de `IMMUTABILITY_SQL` del modelo (con `%` sin duplicar: va por op.execute).
_IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION cameras_audit_log_guard() RETURNS trigger AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'cameras_audit_log es inmutable: UPDATE no permitido';
    END IF;
    IF COALESCE(current_setting('cameras.audit_purge', true), '') = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'cameras_audit_log es inmutable: % no permitido', TG_OP;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_update ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_update
    BEFORE UPDATE ON cameras_audit_log
    FOR EACH ROW EXECUTE FUNCTION cameras_audit_log_guard();

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_delete ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_delete
    BEFORE DELETE ON cameras_audit_log
    FOR EACH ROW EXECUTE FUNCTION cameras_audit_log_guard();

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_truncate ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_truncate
    BEFORE TRUNCATE ON cameras_audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION cameras_audit_log_guard();
"""

_DROP_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_truncate ON cameras_audit_log;
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_delete ON cameras_audit_log;
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_update ON cameras_audit_log;
DROP FUNCTION IF EXISTS cameras_audit_log_guard();
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_table(
        "cameras_dvrs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("location", sa.String(length=150), nullable=True),
        sa.Column("brand", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("channels", sa.SmallInteger(), nullable=True),
        sa.Column("username", sa.String(length=50), nullable=True),
        sa.Column("password_cipher", sa.Text(), nullable=True),
        sa.Column("pattern_cipher", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cameras_dvrs_is_active", "cameras_dvrs", ["is_active"])

    op.create_table(
        "cameras_dvr_departments",
        sa.Column("dvr_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dvr_id"], ["cameras_dvrs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["core_departments.id"]),
        sa.PrimaryKeyConstraint("dvr_id", "department_id"),
    )
    op.create_index("ix_cameras_dvr_departments_department_id", "cameras_dvr_departments", ["department_id"])

    op.create_table(
        "cameras_audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("dvr_id", sa.Integer(), nullable=True),
        sa.Column("dvr_name", sa.String(length=100), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cameras_audit_log_dvr_id", "cameras_audit_log", ["dvr_id"])
    op.create_index("ix_cameras_audit_log_created_at", "cameras_audit_log", ["created_at"])
    op.execute(_IMMUTABILITY_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(_DROP_IMMUTABILITY_SQL)
    op.drop_table("cameras_audit_log")
    op.drop_table("cameras_dvr_departments")
    op.drop_table("cameras_dvrs")
