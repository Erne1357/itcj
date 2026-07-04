"""core_apps: columnas de estilo color/icon_class (badges DB-driven, D7/C4)

Revision ID: o1s2c3p4e004
Revises: o1s2c3p4e003
Create Date: 2026-07-02

Aditivo y nullable (sin server_default). NULL → fallback UI: #6c757d / bi-app.
Backfill de las 6 apps reales vía DML untracked
(database/DML/core_config_2026_07/01_app_colors.sql), NUNCA aquí.
"""
from alembic import op

revision = "o1s2c3p4e004"
down_revision = "o1s2c3p4e003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE core_apps ADD COLUMN IF NOT EXISTS color VARCHAR(7)")
    op.execute("ALTER TABLE core_apps ADD COLUMN IF NOT EXISTS icon_class VARCHAR(50)")


def downgrade():
    op.execute("ALTER TABLE core_apps DROP COLUMN IF EXISTS icon_class")
    op.execute("ALTER TABLE core_apps DROP COLUMN IF EXISTS color")
