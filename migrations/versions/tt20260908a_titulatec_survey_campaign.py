"""titulatec survey + campaign

Encuesta de egresados, cumplimientos de requisitos de cotejo, solicitudes de
auto-inscripcion y el perfil del alumno (core).

Los dos indices UNICOS PARCIALES van con `op.execute`: Alembic no los
autogenera. Los mismos indices estan declarados en el `__table_args__` de su
modelo, que es lo que hace que el `create_all` del CI (base vacia, sin Alembic)
tambien los cree.

Ninguna columna NOT NULL nueva cae sobre una tabla existente: las dos de
`titulatec_cotejo_requirements` son NULL y por eso no llevan `server_default`
(gotcha 8, no aplica).

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(gotcha 1). El entrypoint de dev ya lo hace asi
(`docker/backend/entrypoint-fastapi-dev.sh:38`).

Revision ID: tt20260908a
Revises: d1r2ct0ry02
"""
import sqlalchemy as sa
from alembic import op

revision = "tt20260908a"
down_revision = "d1r2ct0ry02"
branch_labels = None
depends_on = None


def upgrade():
    # -- core_student_profile ------------------------------------------------
    # PK = FK: al llevar ForeignKey, SQLAlchemy no la considera autoincremental
    # y no emite BIGSERIAL. Mismo patron que `titulatec_format_b.process_id`
    # (migrations/versions/f972f1db2ee5_titulatec_initial_schema.py:154-155).
    op.create_table(
        "core_student_profile",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("english_accredited", sa.Boolean(), nullable=True),
        sa.Column("english_accredited_at", sa.Date(), nullable=True),
        sa.Column("english_source", sa.String(length=20), nullable=True),
        sa.Column("contact_email", sa.String(length=150), nullable=True),
        sa.Column("contact_email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("program_id", sa.Integer(), nullable=True),
        sa.Column("program_text", sa.String(length=160), nullable=True),
        sa.Column("reticula", sa.String(length=20), nullable=True),
        sa.Column("estatus_alumno", sa.String(length=40), nullable=True),
        sa.Column("campus", sa.String(length=60), nullable=True),
        sa.Column("curp", sa.String(length=18), nullable=True),
        sa.Column("has_efirma", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["core_programs.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_core_student_profile_contact_email"),
                    "core_student_profile", ["contact_email"], unique=False)

    # -- titulatec_survey_forms ----------------------------------------------
    op.create_table(
        "titulatec_survey_forms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"),
                  nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'draft'"),
                  nullable=False),
        sa.Column("opens_at", sa.Date(), nullable=True),
        sa.Column("closes_at", sa.Date(), nullable=True),
        sa.Column("is_anonymous", sa.Boolean(), server_default=sa.text("FALSE"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version",
                            name="uq_titulatec_survey_forms_code_version"),
    )
    op.create_index(op.f("ix_titulatec_survey_forms_code"),
                    "titulatec_survey_forms", ["code"], unique=False)
    # A lo mas UNA version abierta por codigo. Indice PARCIAL: Alembic no lo
    # autogenera, va literal.
    op.execute(
        "CREATE UNIQUE INDEX uq_titulatec_survey_forms_open "
        "ON titulatec_survey_forms (code) WHERE status = 'open'"
    )

    # -- titulatec_survey_responses ------------------------------------------
    op.create_table(
        "titulatec_survey_responses",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("form_version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("cohort_id", sa.Integer(), nullable=True),
        sa.Column("identity_source", sa.String(length=20), nullable=False),
        sa.Column("control_number", sa.String(length=20), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["titulatec_survey_forms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["process_id"], ["titulatec_processes.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["titulatec_cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_titulatec_survey_responses_form_id"),
                    "titulatec_survey_responses", ["form_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_responses_user_id"),
                    "titulatec_survey_responses", ["user_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_responses_process_id"),
                    "titulatec_survey_responses", ["process_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_responses_cohort_id"),
                    "titulatec_survey_responses", ["cohort_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_responses_control_number"),
                    "titulatec_survey_responses", ["control_number"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_responses_submitted_at"),
                    "titulatec_survey_responses", ["submitted_at"], unique=False)

    # -- titulatec_survey_answers --------------------------------------------
    op.create_table(
        "titulatec_survey_answers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("response_id", sa.BigInteger(), nullable=False),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("field_type", sa.String(length=20), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_num", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["response_id"], ["titulatec_survey_responses.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_titulatec_survey_answers_response_id"),
                    "titulatec_survey_answers", ["response_id"], unique=False)
    op.create_index(op.f("ix_titulatec_survey_answers_field_key"),
                    "titulatec_survey_answers", ["field_key"], unique=False)
    op.create_index("ix_titulatec_survey_answers_key_num",
                    "titulatec_survey_answers", ["field_key", "value_num"],
                    unique=False)

    # -- titulatec_survey_drafts ---------------------------------------------
    op.create_table(
        "titulatec_survey_drafts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["titulatec_survey_forms.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_id", "user_id",
                            name="uq_titulatec_survey_drafts_form_user"),
    )

    # -- titulatec_requirement_fulfillments ----------------------------------
    op.create_table(
        "titulatec_requirement_fulfillments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("requirement_code", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20),
                  server_default=sa.text("'fulfilled'"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_ref", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("label_snapshot", sa.String(length=120), nullable=True),
        sa.Column("checked_by_id", sa.BigInteger(), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["titulatec_processes.id"]),
        # RESTRICT y no CASCADE: ver el comentario del modelo.
        sa.ForeignKeyConstraint(["requirement_id"],
                                ["titulatec_cotejo_requirements.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checked_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("process_id", "requirement_id",
                            name="uq_titulatec_requirement_fulfillments_process_req"),
    )
    op.create_index(op.f("ix_titulatec_requirement_fulfillments_process_id"),
                    "titulatec_requirement_fulfillments", ["process_id"],
                    unique=False)
    op.create_index(op.f("ix_titulatec_requirement_fulfillments_requirement_id"),
                    "titulatec_requirement_fulfillments", ["requirement_id"],
                    unique=False)

    # -- titulatec_enrollment_requests ---------------------------------------
    op.create_table(
        "titulatec_enrollment_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("control_number", sa.String(length=20), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("middle_name", sa.String(length=80), nullable=True),
        sa.Column("program_id", sa.Integer(), nullable=True),
        sa.Column("program_text", sa.String(length=160), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("contact_email", sa.String(length=150), nullable=False),
        sa.Column("has_efirma", sa.Boolean(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20),
                  server_default=sa.text("'unverified'"), nullable=False),
        sa.Column("verify_token_hash", sa.String(length=64), nullable=True),
        sa.Column("verify_expires_at", sa.DateTime(), nullable=True),
        sa.Column("verify_sent_at", sa.DateTime(), nullable=True),
        sa.Column("verify_send_count", sa.Integer(), server_default=sa.text("0"),
                  nullable=False),
        sa.Column("verify_sent_to", sa.String(length=150), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("contact_token_hash", sa.String(length=64), nullable=True),
        sa.Column("contact_expires_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("converted_process_id", sa.Integer(), nullable=True),
        sa.Column("created_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["cohort_id"], ["titulatec_cohorts.id"]),
        sa.ForeignKeyConstraint(["program_id"], ["core_programs.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["converted_process_id"],
                                ["titulatec_processes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_titulatec_enrollment_requests_cohort_id"),
                    "titulatec_enrollment_requests", ["cohort_id"], unique=False)
    op.create_index(op.f("ix_titulatec_enrollment_requests_control_number"),
                    "titulatec_enrollment_requests", ["control_number"],
                    unique=False)
    op.create_index(op.f("ix_titulatec_enrollment_requests_verify_token_hash"),
                    "titulatec_enrollment_requests", ["verify_token_hash"],
                    unique=False)
    op.create_index(op.f("ix_titulatec_enrollment_requests_contact_token_hash"),
                    "titulatec_enrollment_requests", ["contact_token_hash"],
                    unique=False)
    # Una solicitud VIVA por (convocatoria, control). 'rejected' y 'converted'
    # quedan fuera a proposito: deja reintentar tras un rechazo.
    op.execute(
        "CREATE UNIQUE INDEX uq_titulatec_enrollment_req_open "
        "ON titulatec_enrollment_requests (cohort_id, control_number) "
        "WHERE status IN ('unverified','verified','pending_review')"
    )

    # -- columnas nuevas en titulatec_cotejo_requirements --------------------
    op.add_column("titulatec_cotejo_requirements",
                  sa.Column("code", sa.String(length=40), nullable=True))
    op.add_column("titulatec_cotejo_requirements",
                  sa.Column("auto_source", sa.String(length=20), nullable=True))
    op.create_index(op.f("ix_titulatec_cotejo_requirements_code"),
                    "titulatec_cotejo_requirements", ["code"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_titulatec_cotejo_requirements_code"),
                  table_name="titulatec_cotejo_requirements")
    op.drop_column("titulatec_cotejo_requirements", "auto_source")
    op.drop_column("titulatec_cotejo_requirements", "code")

    op.execute("DROP INDEX IF EXISTS uq_titulatec_enrollment_req_open")
    op.drop_index(op.f("ix_titulatec_enrollment_requests_contact_token_hash"),
                  table_name="titulatec_enrollment_requests")
    op.drop_index(op.f("ix_titulatec_enrollment_requests_verify_token_hash"),
                  table_name="titulatec_enrollment_requests")
    op.drop_index(op.f("ix_titulatec_enrollment_requests_control_number"),
                  table_name="titulatec_enrollment_requests")
    op.drop_index(op.f("ix_titulatec_enrollment_requests_cohort_id"),
                  table_name="titulatec_enrollment_requests")
    op.drop_table("titulatec_enrollment_requests")

    op.drop_index(op.f("ix_titulatec_requirement_fulfillments_requirement_id"),
                  table_name="titulatec_requirement_fulfillments")
    op.drop_index(op.f("ix_titulatec_requirement_fulfillments_process_id"),
                  table_name="titulatec_requirement_fulfillments")
    op.drop_table("titulatec_requirement_fulfillments")

    op.drop_table("titulatec_survey_drafts")

    op.drop_index("ix_titulatec_survey_answers_key_num",
                  table_name="titulatec_survey_answers")
    op.drop_index(op.f("ix_titulatec_survey_answers_field_key"),
                  table_name="titulatec_survey_answers")
    op.drop_index(op.f("ix_titulatec_survey_answers_response_id"),
                  table_name="titulatec_survey_answers")
    op.drop_table("titulatec_survey_answers")

    op.drop_index(op.f("ix_titulatec_survey_responses_submitted_at"),
                  table_name="titulatec_survey_responses")
    op.drop_index(op.f("ix_titulatec_survey_responses_control_number"),
                  table_name="titulatec_survey_responses")
    op.drop_index(op.f("ix_titulatec_survey_responses_cohort_id"),
                  table_name="titulatec_survey_responses")
    op.drop_index(op.f("ix_titulatec_survey_responses_process_id"),
                  table_name="titulatec_survey_responses")
    op.drop_index(op.f("ix_titulatec_survey_responses_user_id"),
                  table_name="titulatec_survey_responses")
    op.drop_index(op.f("ix_titulatec_survey_responses_form_id"),
                  table_name="titulatec_survey_responses")
    op.drop_table("titulatec_survey_responses")

    op.execute("DROP INDEX IF EXISTS uq_titulatec_survey_forms_open")
    op.drop_index(op.f("ix_titulatec_survey_forms_code"),
                  table_name="titulatec_survey_forms")
    op.drop_table("titulatec_survey_forms")

    op.drop_index(op.f("ix_core_student_profile_contact_email"),
                  table_name="core_student_profile")
    op.drop_table("core_student_profile")
