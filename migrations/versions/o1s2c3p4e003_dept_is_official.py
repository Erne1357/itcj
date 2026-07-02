"""departamentos: flag is_official (organigrama oficial vs sub-depto creado)

Revision ID: o1s2c3p4e003
Revises: o1s2c3p4e002
Create Date: 2026-07-02

Aditivo. Todos los departamentos existentes quedan is_official=TRUE (hoy solo hay
oficiales dados de alta por seed). Lo creado luego por la UI nace is_official=FALSE.
"""
from alembic import op

revision = "o1s2c3p4e003"
down_revision = "o1s2c3p4e002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE core_departments "
        "ADD COLUMN IF NOT EXISTS is_official BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_departments_is_official ON core_departments(is_official)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_departments_is_official")
    op.execute("ALTER TABLE core_departments DROP COLUMN IF EXISTS is_official")
