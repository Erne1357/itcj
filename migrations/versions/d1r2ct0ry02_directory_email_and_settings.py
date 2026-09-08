"""directory email and settings

Añade directory_entries.email y la tabla singleton directory_settings.
La fila 1 se siembra aquí: es el único lugar que corre en todos los entornos con
esquema real (CI usa create_all y no pasa por aquí, por eso los lectores toleran
que la fila no exista).

Revision ID: d1r2ct0ry02
Revises: tt20260903a
"""
import sqlalchemy as sa
from alembic import op

revision = "d1r2ct0ry02"
down_revision = "tt20260903a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "directory_entries",
        sa.Column("email", sa.String(length=150), nullable=True),
    )
    op.create_table(
        "directory_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "show_unofficial_departments",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_directory_settings"),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["core_users.id"], name="fk_directory_settings_updated_by"
        ),
        sa.CheckConstraint("id = 1", name="ck_directory_settings_singleton"),
    )
    op.execute(
        "INSERT INTO directory_settings (id, show_unofficial_departments) "
        "VALUES (1, false) ON CONFLICT (id) DO NOTHING"
    )


def downgrade():
    op.drop_table("directory_settings")
    op.drop_column("directory_entries", "email")
