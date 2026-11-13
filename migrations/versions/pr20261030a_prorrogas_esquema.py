"""prorrogas_tec: esquema nuevo de solicitudes, documentos, firmas, invitaciones y bitacora

Escrita a mano (sin autogenerate), junto con los modelos de
`itcj2/apps/prorrogas_tec/models/`: el CI arma el esquema con `create_all` y
dev/prod con Alembic, asi que tablas, CHECK e indices se declaran AQUI y en los
modelos con los mismos nombres.

Spec: docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md (§9).

Que hace
--------
Tira las cinco tablas del fork (`prorrogas_payments`, `prorrogas_requests`,
`prorrogas_payments_options`, `prorrogas_notifications`, `prorrogas_period_config`)
y sus tipos enum, y crea `prorrogas_requests` (nueva), `prorrogas_documents`,
`prorrogas_signatures`, `prorrogas_invitations`, `prorrogas_joins` y
`prorrogas_events`.

Downgrade (CON PERDIDA)
-----------------------
Tira las seis tablas nuevas y NO restaura las del fork. CON PERDIDA; la rama no
esta en produccion.

Revision ID: pr20261030a
Revises: pr20261029a
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "pr20261030a"
down_revision = "pr20261029a"
branch_labels = None
depends_on = None

_NUEVAS = ("prorrogas_events", "prorrogas_joins", "prorrogas_invitations",
           "prorrogas_signatures", "prorrogas_documents", "prorrogas_requests")


def upgrade():
    op.execute(
        "DROP TABLE IF EXISTS prorrogas_payments, prorrogas_requests, prorrogas_payments_options, "
        "prorrogas_notifications, prorrogas_period_config CASCADE"
    )
    op.execute("DROP TYPE IF EXISTS request_status_pg_enum, payment_status_pg_enum")

    now = sa.text("NOW()")
    op.create_table(
        "prorrogas_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(10), server_default="app", nullable=False),
        sa.Column("import_ref", sa.String(80), nullable=True),
        sa.Column("student_id", sa.BigInteger(), nullable=True),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("period_label", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), server_default="pendiente", nullable=False),
        sa.Column("requested_terms", sa.SmallInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("control_number", sa.Text(), nullable=False),
        sa.Column("student_name", sa.Text(), nullable=False),
        sa.Column("program_name", sa.Text(), nullable=True),
        sa.Column("program_level", sa.String(20), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
        sa.CheckConstraint("origin IN ('app','excel')", name="ck_prorrogas_requests_origin"),
        sa.CheckConstraint("origin = 'excel' OR student_id IS NOT NULL", name="ck_prorrogas_requests_student"),
        sa.CheckConstraint("status IN ('pendiente','aceptada','rechazada','cancelada')",
                           name="ck_prorrogas_requests_status"),
        sa.CheckConstraint("requested_terms BETWEEN 1 AND 3", name="ck_prorrogas_requests_terms"),
        sa.ForeignKeyConstraint(["student_id"], ["core_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["period_id"], ["core_academic_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_ref"),
    )
    op.create_index(
        "uq_prorrogas_requests_abierta", "prorrogas_requests", ["student_id", "period_id"], unique=True,
        postgresql_where=sa.text("status IN ('pendiente','aceptada') AND origin = 'app'"),
    )
    op.create_index("ix_prorrogas_requests_estado", "prorrogas_requests", ["status", "created_at"])

    op.create_table(
        "prorrogas_documents",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("doc_type", sa.String(40), nullable=True),
        sa.Column("version", sa.SmallInteger(), nullable=True),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("generated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), server_default=now, nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["prorrogas_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["prorrogas_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "doc_type", "version", name="uq_prorrogas_documents_version"),
    )

    op.create_table(
        "prorrogas_signatures",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("signer_id", sa.BigInteger(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["prorrogas_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signer_id"], ["core_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "prorrogas_invitations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("control_number", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("user_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_sha256"),
    )

    op.create_table(
        "prorrogas_joins",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("via", sa.String(12), nullable=True),
        sa.Column("invitation_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_by_id", sa.BigInteger(), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("via IN ('qr','invitacion')", name="ck_prorrogas_joins_via"),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["prorrogas_invitations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issued_by_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prorrogas_joins_usuario", "prorrogas_joins", ["user_id", "joined_at"])

    op.create_table(
        "prorrogas_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["prorrogas_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["core_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prorrogas_events_solicitud", "prorrogas_events", ["request_id", "created_at"])


def downgrade():
    for t in _NUEVAS:
        op.drop_table(t)
