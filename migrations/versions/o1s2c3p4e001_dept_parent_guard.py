"""department parent_id index + self-parent check guard

Revision ID: o1s2c3p4e001
Revises: a1d1r3ctory01
Create Date: 2026-07-02

Aditivo/non-breaking: índice en core_departments.parent_id (hot filter) y un
CHECK que impide que un departamento sea su propio padre. Los ciclos de más de
un salto se validan en la capa de servicio (update_department).
"""
from alembic import op

revision = "o1s2c3p4e001"
down_revision = "a1d1r3ctory01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_departments_parent_id", "core_departments", ["parent_id"],
        if_not_exists=True,
    )
    op.create_check_constraint(
        "ck_departments_no_self_parent",
        "core_departments",
        "parent_id IS NULL OR parent_id <> id",
    )


def downgrade():
    op.drop_constraint("ck_departments_no_self_parent", "core_departments", type_="check")
    op.drop_index("ix_departments_parent_id", table_name="core_departments")
