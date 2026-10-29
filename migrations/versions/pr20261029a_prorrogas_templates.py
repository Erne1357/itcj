"""prorrogas_tec: plantillas .docx por año (prorrogas_templates)

Escrita a mano (sin autogenerate: la deriva de modelos de otras apps borraria
cosas que no son de esta entrega), junto con `models/template.py`: el CI arma el
esquema con `create_all` y dev/prod con Alembic, asi que la tabla, el CHECK y el
indice se declaran AQUI y en el modelo con los mismos nombres.

Spec: docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md (§6.3, §9).

Que agrega
----------
`prorrogas_templates`: una fila por plantilla que sube la secretaria para un
formato (`doc_type`) y un año. No se edita ni se borra: la mas reciente de su
(formato, año) es la que se usa. El archivo vive en disco bajo
`PRORROGAS_UPLOAD_PATH` (`file_path` es relativa).

Downgrade (CON PERDIDA)
-----------------------
Tira la tabla: se pierde el registro de que plantillas subio la secretaria (los
archivos quedan en disco). Las cartas vuelven a salir con la plantilla del
sistema.

Revision ID: pr20261029a
Revises: 53cfd4188f65
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "pr20261029a"
down_revision = "53cfd4188f65"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prorrogas_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("placeholders", sa.JSON(), nullable=False),
        sa.Column("uploaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("year BETWEEN 2020 AND 2100", name="ck_prorrogas_templates_year"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prorrogas_templates_tipo_anio",
        "prorrogas_templates", ["doc_type", "year", "uploaded_at"], unique=False,
    )


def downgrade():
    op.drop_index("ix_prorrogas_templates_tipo_anio", table_name="prorrogas_templates")
    op.drop_table("prorrogas_templates")
