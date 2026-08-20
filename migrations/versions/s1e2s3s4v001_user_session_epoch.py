"""core_users.session_epoch: fuente de verdad de la revocación de sesión

Revision ID: s1e2s3s4v001
Revises: f6feb1cdc56a
Create Date: 2026-08-20

Aditiva y con server_default: la tabla ya tiene filas y la columna es NOT NULL.
Los usuarios existentes arrancan en 0, que es exactamente lo que `current_version`
devolvía para ellos cuando la clave de Redis no existía — así el despliegue no
cambia el veredicto de ningún token vivo.
"""
from alembic import op
import sqlalchemy as sa

revision = "s1e2s3s4v001"
down_revision = "f6feb1cdc56a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "core_users",
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("core_users", "session_epoch")
