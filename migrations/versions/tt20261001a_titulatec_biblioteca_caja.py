"""titulatec: no adeudo de biblioteca (Biblioteca -> Caja) y constancias por lote

Spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.1. Escrita a mano
(sin autogenerate), junto con los modelos de la misma tarea: los nombres de
tabla/indice/CHECK de abajo estan declarados AQUI y en
`models/library_clearance.py`, `models/certificate.py`,
`models/prior_clearance.py`, `models/cohort.py` y `models/survey_review.py`
porque el CI arma el esquema con `create_all` (sin Alembic) y dev/prod lo
arman con Alembic -- si divergen, una base ve una tabla/indice/CHECK que la
otra no tiene.

Que agrega
----------
1. `titulatec_certificate_batches` / `titulatec_certificates` (con el
   indice parcial «por imprimir» y el UNIQUE parcial «a lo mas una vigente
   por origen», `uq_titulatec_certificates_live_source`, Ruling R29) /
   `titulatec_certificate_counters` / `titulatec_prior_clearances`: motor de
   constancias (§4.1.3-6).
2. `titulatec_library_clearances`: no adeudo de biblioteca, una fila por
   proceso (§4.1.1), con los 4 CHECK de dinero (`total = debt + donation`,
   los tres `>= 0`).
3. `titulatec_cohorts.book_donation_amount` NULL + CHECK `>= 0` (§4.1.2).
4. `titulatec_survey_reviews`: `response_id` pasa a NULLABLE, `origin`
   NOT NULL con default `'submission'`, `prior_issued_on` NULL (§4.1.7).

Backfill (SOLO datos, patron `tt20260929a`)
--------------------------------------------
Por cada proceso `status IN ('active','on_hold')` cuya fase 2
(`ProcessPhase.phase_number = 2`) NO esta `approved` (sin fila cuenta como
NO aprobada) y que TODAVIA no tiene fila en `titulatec_library_clearances`:
inserta `cleared`/`cleared_via='legacy'` si tiene un `RequirementFulfillment`
`fulfilled|waived` del requisito `code='library_clearance'` de SU
convocatoria (`titulatec_cotejo_requirements.cohort_id = proceso.cohort_id`);
si no, `pending`. Usa subconsultas `EXISTS` (no `LEFT JOIN`) a proposito: un
`LEFT JOIN` contra fulfillments/requisitos podria multiplicar filas por
proceso si alguna convocatoria llegara a tener mas de un requisito con ese
`code`, y esta tabla tiene UNIQUE por proceso -- el `INSERT` reventaria a
medias. Idempotente (filtra por "sin fila todavia"): correrla dos veces, o
que la vuelva a correr el comando de re-backfill de una tarea posterior
(Review Focus #5, procesos creados en el blue/green sin fila), no duplica.

Downgrade (CON PERDIDA, documentada)
-------------------------------------
1. Borra `titulatec_survey_reviews` con `origin='prior'` y los
   `RequirementFulfillment` con `external_ref LIKE 'survey_prior:%'` que
   esas previas hayan generado -- ANTES de regresar `response_id` a NOT
   NULL, porque una previa no tiene respuesta real detras (unico caso con
   `response_id IS NULL`). Los cumplimientos `library_clearance` YA escritos
   (via Biblioteca/Caja/SE, no el patron `survey_prior:%`) se CONSERVAN: no
   son parte de esta feature, son creditos reales del requisito.
2. Regresa `auto_source` a NULL en los requisitos `code='library_clearance'`:
   el codigo viejo (anterior a este deploy) trata cualquier `auto_source` no
   nulo como «lo acredita el sistema» y el encargado ya no podria marcarlo a
   mano.
3. Borra las 5 tablas nuevas (certificates antes que certificate_batches:
   la primera tiene FK a la segunda) y las columnas nuevas de cohorts y
   survey_reviews.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261001a
Revises: tt20260930a
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261001a"
down_revision = "tt20260930a"
branch_labels = None
depends_on = None


# --- Backfill (upgrade) -----------------------------------------------------
# EXISTS, no LEFT JOIN: ver docstring del modulo.
BACKFILL_SQL = """
INSERT INTO titulatec_library_clearances
    (process_id, status, cleared_via, created_at, updated_at)
SELECT
    p.id,
    CASE WHEN EXISTS (
        SELECT 1
          FROM titulatec_requirement_fulfillments rf
          JOIN titulatec_cotejo_requirements req ON req.id = rf.requirement_id
         WHERE rf.process_id = p.id
           AND req.cohort_id = p.cohort_id
           AND req.code = 'library_clearance'
           AND rf.status IN ('fulfilled', 'waived')
    ) THEN 'cleared' ELSE 'pending' END,
    CASE WHEN EXISTS (
        SELECT 1
          FROM titulatec_requirement_fulfillments rf
          JOIN titulatec_cotejo_requirements req ON req.id = rf.requirement_id
         WHERE rf.process_id = p.id
           AND req.cohort_id = p.cohort_id
           AND req.code = 'library_clearance'
           AND rf.status IN ('fulfilled', 'waived')
    ) THEN 'legacy' ELSE NULL END,
    NOW(),
    NOW()
  FROM titulatec_processes p
 WHERE p.status IN ('active', 'on_hold')
   AND NOT EXISTS (
       SELECT 1 FROM titulatec_process_phases ph
        WHERE ph.process_id = p.id AND ph.phase_number = 2 AND ph.status = 'approved'
   )
   AND NOT EXISTS (
       SELECT 1 FROM titulatec_library_clearances lc WHERE lc.process_id = p.id
   )
"""

# --- Downgrade: previas y su rastro --------------------------------------
DOWNGRADE_DELETE_PRIOR_FULFILLMENTS_SQL = """
DELETE FROM titulatec_requirement_fulfillments
 WHERE external_ref LIKE 'survey_prior:%'
"""

DOWNGRADE_DELETE_PRIOR_REVIEWS_SQL = """
DELETE FROM titulatec_survey_reviews WHERE origin = 'prior'
"""

DOWNGRADE_RESET_AUTO_SOURCE_SQL = """
UPDATE titulatec_cotejo_requirements
   SET auto_source = NULL
 WHERE code = 'library_clearance'
"""


def upgrade() -> None:
    # --- 1. Motor de constancias --------------------------------------------
    op.create_table(
        "titulatec_certificate_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "titulatec_certificates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=False),
        sa.Column("control_number", sa.String(length=20), nullable=False),
        sa.Column("student_name", sa.String(length=200), nullable=False),
        sa.Column("program_name", sa.String(length=200), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("issued_by_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by_id", sa.BigInteger(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["process_id"], ["titulatec_processes.id"]),
        sa.ForeignKeyConstraint(["issued_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["titulatec_certificate_batches.id"]),
        sa.ForeignKeyConstraint(["voided_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_titulatec_certificates_number", "titulatec_certificates",
                    ["number"], unique=True)
    op.create_index("ix_titulatec_certificates_process_id", "titulatec_certificates",
                    ["process_id"])
    op.create_index("ix_titulatec_certificates_batch_id", "titulatec_certificates",
                    ["batch_id"])
    op.create_index(
        "ix_titulatec_certificates_pending_print", "titulatec_certificates",
        ["kind", "issued_at"],
        postgresql_where=sa.text("batch_id IS NULL AND voided_at IS NULL"),
    )
    # A lo mas UNA constancia vigente por origen (spec §5 invariante 5,
    # Ruling R29 de la revision final): la anulada sale del indice, asi que
    # una anulada y su reemplazo conviven; dos vigentes del mismo
    # `source_ref` truenan.
    op.create_index(
        "uq_titulatec_certificates_live_source", "titulatec_certificates",
        ["source_ref"], unique=True,
        postgresql_where=sa.text("voided_at IS NULL"),
    )

    op.create_table(
        "titulatec_certificate_counters",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("kind", "year"),
    )

    op.create_table(
        "titulatec_prior_clearances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("control_number", sa.String(length=20), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("applied_process_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["applied_process_id"], ["titulatec_processes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "control_number",
                            name="uq_titulatec_prior_clearances_kind_control"),
    )
    op.create_index("ix_titulatec_prior_clearances_control_number",
                    "titulatec_prior_clearances", ["control_number"])

    # --- 2. No adeudo de biblioteca ------------------------------------------
    op.create_table(
        "titulatec_library_clearances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("cleared_via", sa.String(length=20), nullable=True),
        sa.Column("debt_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("donation_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("library_note", sa.Text(), nullable=True),
        sa.Column("library_by_id", sa.BigInteger(), nullable=True),
        sa.Column("library_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("paid_by_id", sa.BigInteger(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("receipt_number", sa.String(length=40), nullable=True),
        sa.Column("prior_issued_on", sa.Date(), nullable=True),
        sa.Column("prior_note", sa.Text(), nullable=True),
        sa.Column("prior_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["process_id"], ["titulatec_processes.id"]),
        sa.ForeignKeyConstraint(["library_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["paid_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["prior_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("process_id", name="uq_titulatec_library_clearances_process"),
        sa.CheckConstraint(
            "total_amount IS NULL OR debt_amount IS NULL OR donation_amount IS NULL "
            "OR total_amount = debt_amount + donation_amount",
            name="ck_titulatec_library_clearances_total_eq_sum",
        ),
        sa.CheckConstraint("debt_amount IS NULL OR debt_amount >= 0",
                           name="ck_titulatec_library_clearances_debt_nonneg"),
        sa.CheckConstraint("donation_amount IS NULL OR donation_amount >= 0",
                           name="ck_titulatec_library_clearances_donation_nonneg"),
        sa.CheckConstraint("total_amount IS NULL OR total_amount >= 0",
                           name="ck_titulatec_library_clearances_total_nonneg"),
    )
    op.create_index("ix_titulatec_library_clearances_status",
                    "titulatec_library_clearances", ["status"])

    # --- 3. Donacion de convocatoria ------------------------------------------
    op.add_column("titulatec_cohorts",
                  sa.Column("book_donation_amount", sa.Numeric(10, 2), nullable=True))
    op.create_check_constraint(
        "ck_titulatec_cohorts_book_donation", "titulatec_cohorts",
        "book_donation_amount IS NULL OR book_donation_amount >= 0")

    # --- 4. Solicitudes de liberacion: previas ---------------------------------
    op.add_column("titulatec_survey_reviews",
                  sa.Column("origin", sa.String(length=20), nullable=False,
                            server_default=sa.text("'submission'")))
    op.add_column("titulatec_survey_reviews",
                  sa.Column("prior_issued_on", sa.Date(), nullable=True))
    op.alter_column("titulatec_survey_reviews", "response_id",
                    existing_type=sa.BigInteger(), nullable=True)

    # --- Backfill (solo datos) -------------------------------------------------
    op.execute(sa.text(BACKFILL_SQL))


def downgrade() -> None:
    # --- Previas y su rastro, ANTES de poder exigir response_id NOT NULL -----
    op.execute(sa.text(DOWNGRADE_DELETE_PRIOR_FULFILLMENTS_SQL))
    op.execute(sa.text(DOWNGRADE_DELETE_PRIOR_REVIEWS_SQL))

    op.alter_column("titulatec_survey_reviews", "response_id",
                    existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("titulatec_survey_reviews", "prior_issued_on")
    op.drop_column("titulatec_survey_reviews", "origin")

    op.drop_constraint("ck_titulatec_cohorts_book_donation", "titulatec_cohorts",
                       type_="check")
    op.drop_column("titulatec_cohorts", "book_donation_amount")

    # El codigo viejo trata cualquier auto_source no nulo como «lo acredita
    # el sistema»: hay que devolverlo a NULL o el encargado ya no podria
    # marcar el requisito a mano.
    op.execute(sa.text(DOWNGRADE_RESET_AUTO_SOURCE_SQL))

    op.drop_index("ix_titulatec_library_clearances_status",
                  table_name="titulatec_library_clearances")
    op.drop_table("titulatec_library_clearances")

    op.drop_index("ix_titulatec_prior_clearances_control_number",
                  table_name="titulatec_prior_clearances")
    op.drop_table("titulatec_prior_clearances")

    op.drop_table("titulatec_certificate_counters")

    # IF EXISTS: este indice se agrego editando la revision EN SITIO (Ruling
    # R29, antes de llegar a produccion); una base migrada con el texto
    # anterior (la de dev) no lo tiene y el DROP pelado abortaba la bajada.
    op.drop_index("uq_titulatec_certificates_live_source",
                  table_name="titulatec_certificates", if_exists=True)
    op.drop_index("ix_titulatec_certificates_pending_print",
                  table_name="titulatec_certificates")
    op.drop_index("ix_titulatec_certificates_batch_id", table_name="titulatec_certificates")
    op.drop_index("ix_titulatec_certificates_process_id", table_name="titulatec_certificates")
    op.drop_index("ix_titulatec_certificates_number", table_name="titulatec_certificates")
    op.drop_table("titulatec_certificates")

    op.drop_table("titulatec_certificate_batches")
