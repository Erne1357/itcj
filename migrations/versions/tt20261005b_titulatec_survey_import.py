"""titulatec: respuestas importadas del Excel de Forms y «constancia por recoger»

Spec `2026-10-05-titulatec-import-encuesta-xlsx-design.md` §4.1. Escrita a
mano (sin autogenerate), junto con los modelos: el CI arma el esquema con
`create_all` (sin Alembic) y dev/prod con Alembic -- columnas e indice estan
declarados AQUI y en el modelo, con el mismo nombre y tipo.

Que agrega
----------
* `titulatec_survey_responses.import_ref` String(120) NULL + indice UNICO
  PARCIAL `uq_titulatec_survey_responses_form_import_ref` sobre
  `(form_id, import_ref) WHERE import_ref IS NOT NULL` (R6: re-correr el mismo
  archivo no duplica). `identity_source` gana el valor `import`: es
  String(20) SIN CHECK de dominio, no hay restriccion que cambiar.
* `titulatec_survey_answers.is_raw` Boolean NOT NULL `server_default false`
  (D1: valor guardado tal cual porque no encajo con el campo).
* `titulatec_survey_reviews.paper_pending` Boolean NOT NULL `server_default
  false`, `paper_delivered_at` DateTime NULL, `paper_delivered_by_id`
  BigInteger FK `core_users.id` NULL (D3; nombre de FK por omision de
  Postgres, como `create_all`).
* `titulatec_prior_clearances.response_id` BigInteger FK
  `titulatec_survey_responses.id` NULL `ON DELETE SET NULL`, `paper_pending`
  Boolean NOT NULL `server_default false` (R7).

Sin backfill: ninguna fila existente es importada ni tiene papel pendiente.

Downgrade (CON PERDIDA, documentada)
-------------------------------------
Borra el indice y las columnas: se pierden `import_ref`, `is_raw`, la marca
de papel pendiente/entregado y la liga diferida respuesta<->previa. Las filas
con `identity_source='import'` SE CONSERVAN (la columna sigue siendo un
String; el codigo viejo solo las veria como un valor que no conoce). Re-correr
el import tras un downgrade+upgrade las DUPLICARIA (ya sin `import_ref`):
borrar antes las filas 'import' si se piensa reimportar.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261005b
Revises: tt20261005a
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261005b"
down_revision = "tt20261005a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("titulatec_survey_responses",
                  sa.Column("import_ref", sa.String(length=120), nullable=True))
    op.create_index("uq_titulatec_survey_responses_form_import_ref",
                    "titulatec_survey_responses", ["form_id", "import_ref"],
                    unique=True,
                    postgresql_where=sa.text("import_ref IS NOT NULL"))

    op.add_column("titulatec_survey_answers",
                  sa.Column("is_raw", sa.Boolean(), nullable=False,
                            server_default=sa.text("FALSE")))

    op.add_column("titulatec_survey_reviews",
                  sa.Column("paper_pending", sa.Boolean(), nullable=False,
                            server_default=sa.text("FALSE")))
    op.add_column("titulatec_survey_reviews",
                  sa.Column("paper_delivered_at", sa.DateTime(), nullable=True))
    op.add_column("titulatec_survey_reviews",
                  sa.Column("paper_delivered_by_id", sa.BigInteger(),
                            sa.ForeignKey("core_users.id"), nullable=True))

    op.add_column("titulatec_prior_clearances",
                  sa.Column("response_id", sa.BigInteger(),
                            sa.ForeignKey("titulatec_survey_responses.id",
                                          ondelete="SET NULL"),
                            nullable=True))
    op.add_column("titulatec_prior_clearances",
                  sa.Column("paper_pending", sa.Boolean(), nullable=False,
                            server_default=sa.text("FALSE")))


def downgrade() -> None:
    # DROP COLUMN se lleva sus FKs con ella.
    op.drop_column("titulatec_prior_clearances", "paper_pending")
    op.drop_column("titulatec_prior_clearances", "response_id")
    op.drop_column("titulatec_survey_reviews", "paper_delivered_by_id")
    op.drop_column("titulatec_survey_reviews", "paper_delivered_at")
    op.drop_column("titulatec_survey_reviews", "paper_pending")
    op.drop_column("titulatec_survey_answers", "is_raw")
    op.drop_index("uq_titulatec_survey_responses_form_import_ref",
                  table_name="titulatec_survey_responses")
    op.drop_column("titulatec_survey_responses", "import_ref")
