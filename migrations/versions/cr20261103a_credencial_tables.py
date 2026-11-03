"""credencial: fotos de credencial y bitacora de verificaciones

Revision ID: cr20261103a
Revises: d1r3ct0ry03
"""
import sqlalchemy as sa
from alembic import op

revision = "cr20261103a"
down_revision = "d1r3ct0ry03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credencial_photos",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ref", sa.String(length=24), nullable=False),
        sa.Column("file_name", sa.String(length=40), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("file_name"),
    )
    op.create_index("ix_credencial_photos_ref", "credencial_photos", ["ref"], unique=True)

    op.create_table(
        "credencial_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("verifier_id", sa.BigInteger(), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("token_issued_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("result IN ('valid','inactive')", name="ck_credencial_verifications_result"),
        sa.ForeignKeyConstraint(["student_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verifier_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credencial_verifications_student_id", "credencial_verifications", ["student_id"])
    op.create_index("ix_credencial_verifications_verifier_id", "credencial_verifications", ["verifier_id"])
    op.create_index("ix_credencial_verifications_verified_at", "credencial_verifications", ["verified_at"])


def downgrade() -> None:
    op.drop_table("credencial_verifications")
    op.drop_index("ix_credencial_photos_ref", table_name="credencial_photos")
    op.drop_table("credencial_photos")
