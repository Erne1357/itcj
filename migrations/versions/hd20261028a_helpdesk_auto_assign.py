"""helpdesk: settings singleton y reglas de asignacion automatica

Revision ID: hd20261028a
Revises: tt20261015a
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "hd20261028a"
down_revision = "tt20261015a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("auto_assign_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("assignment_email_user_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_helpdesk_settings_singleton"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO helpdesk_settings (id) VALUES (1)")

    op.create_table(
        "helpdesk_assignment_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(30), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=True),
        sa.Column("strategy", sa.String(20), nullable=False),
        sa.Column("technician_ids", sa.JSON(), nullable=False),
        sa.Column("last_assigned_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("strategy IN ('round_robin','least_loaded')", name="ck_helpdesk_assignment_rules_strategy"),
        sa.ForeignKeyConstraint(["category_id"], ["helpdesk_category.id"]),
        sa.ForeignKeyConstraint(["last_assigned_user_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_helpdesk_assignment_rules_area_active",
        "helpdesk_assignment_rules", ["area", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_helpdesk_assignment_rules_area_active", table_name="helpdesk_assignment_rules")
    op.drop_table("helpdesk_assignment_rules")
    op.drop_table("helpdesk_settings")
