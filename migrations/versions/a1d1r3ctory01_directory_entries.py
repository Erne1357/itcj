"""directory_entries

Revision ID: a1d1r3ctory01
Revises: 742c0440efa1
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "a1d1r3ctory01"
down_revision = "742c0440efa1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "directory_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("holder_name", sa.String(length=120), nullable=True),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("notes", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["department_id"], ["core_departments.id"]),
        sa.ForeignKeyConstraint(["position_id"], ["core_positions.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_directory_entries_department_id", "directory_entries", ["department_id"])
    op.create_index("ix_directory_entries_position_id", "directory_entries", ["position_id"])
    op.create_index("ix_directory_entries_extension", "directory_entries", ["extension"])
    op.create_index("ix_directory_entries_is_active", "directory_entries", ["is_active"])


def downgrade():
    op.drop_index("ix_directory_entries_is_active", table_name="directory_entries")
    op.drop_index("ix_directory_entries_extension", table_name="directory_entries")
    op.drop_index("ix_directory_entries_position_id", table_name="directory_entries")
    op.drop_index("ix_directory_entries_department_id", table_name="directory_entries")
    op.drop_table("directory_entries")
