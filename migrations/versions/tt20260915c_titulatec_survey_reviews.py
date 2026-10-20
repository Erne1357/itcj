"""titulatec: tabla de solicitudes de liberacion GTV de la encuesta de egresados

Gestion Tecnologica y Vinculacion (GTV) revisa la encuesta de egresados que ya
se envio y decide si libera el requisito de cotejo `graduate_survey` o deja
observaciones. Una fila por proceso (`process_id` UNIQUE): nace al enviar la
encuesta y es la misma fila la que GTV libera, observa o revoca despues.

Escrita a mano (no autogenerate): solo `CREATE TABLE` e indices, no toca
ninguna fila existente. Correr con MIGRATE_DATABASE_URL (Postgres directo),
nunca contra PgBouncer (gotcha 1).

Revision ID: tt20260915c
Revises: tt20260915b
"""
import sqlalchemy as sa
from alembic import op

revision = "tt20260915c"
down_revision = "tt20260915b"
branch_labels = None
depends_on = None

_TABLE = "titulatec_survey_reviews"


def upgrade():
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("response_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20),
                  server_default=sa.text("'in_review'"), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["titulatec_processes.id"]),
        sa.ForeignKeyConstraint(["response_id"], ["titulatec_survey_responses.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("process_id", name="uq_titulatec_survey_reviews_process"),
    )
    op.create_index(op.f("ix_titulatec_survey_reviews_response_id"),
                    _TABLE, ["response_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_reviews_status"),
                    _TABLE, ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_titulatec_survey_reviews_status"), table_name=_TABLE)
    op.drop_index(op.f("ix_titulatec_survey_reviews_response_id"), table_name=_TABLE)
    op.drop_table(_TABLE)
