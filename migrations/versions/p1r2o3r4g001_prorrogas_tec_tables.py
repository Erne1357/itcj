"""prorrogas_tec: tablas de la app de prórrogas de pago

Revision ID: p1r2o3r4g001
Revises: s1e2s3s4v001
Create Date: 2026-09-01

Alta inicial de la app `prorrogas_tec`, importada del fork donde estuvo
congelada desde junio de 2026. Ese fork llevaba las prórrogas dentro de una
única migración squash (`cda9958f1265`, "Migracion_inicial") que recreaba el
esquema ENTERO de la plataforma; aplicarla aquí habría chocado con las 68
revisiones que esta rama sí tiene. Se extrajo de ahí SOLO el DDL de las cinco
tablas de la app, encadenado sobre el head real (`s1e2s3s4v001`).

Los dos ENUM se crean EXPLÍCITAMENTE antes de las tablas: los modelos los
declaran con `create_type=False` (`models/request.py`, `models/payments.py`),
así que SQLAlchemy no emite el `CREATE TYPE` por su cuenta y el `create_table`
fallaría con "type does not exist". Es el mismo motivo por el que el paso de
esquema del CI (`.github/workflows/deploy.yml`) los crea a mano antes de
`create_all`.

Orden de creación: las tablas se crean respetando las FK
(`payments_options` → `requests` → `payments`), y el downgrade las tira al
revés antes de soltar los tipos.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "p1r2o3r4g001"
down_revision = "s1e2s3s4v001"
branch_labels = None
depends_on = None


_REQUEST_STATUS = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED",
    name="request_status_pg_enum",
    create_type=False,
)
_PAYMENT_STATUS = postgresql.ENUM(
    "PENDING", "APPROVED", "MIDDLE", "NOPAID",
    name="payment_status_pg_enum",
    create_type=False,
)


def upgrade():
    bind = op.get_bind()
    # checkfirst: la migración tiene que poder re-aplicarse sobre una BD donde
    # los tipos ya existan (p. ej. una restaurada de un dump del fork).
    _REQUEST_STATUS.create(bind, checkfirst=True)
    _PAYMENT_STATUS.create(bind, checkfirst=True)

    # Ventana de solicitudes por período académico. `period_id` es UNIQUE: un
    # período tiene como mucho una configuración de prórrogas (espejo de
    # agendatec_period_config).
    op.create_table(
        "prorrogas_period_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("student_admission_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("student_admission_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_1", sa.DateTime(), nullable=True),
        sa.Column("payment_2", sa.DateTime(), nullable=True),
        sa.Column("payment_3", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["core_academic_periods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_id"),
    )

    # Catálogo de montos/planes de pago. Va ANTES de `prorrogas_requests`, que
    # la referencia por `total_amount_id`.
    op.create_table(
        "prorrogas_payments_options",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("total_payment", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["period_id"], ["core_academic_periods.id"],
            onupdate="CASCADE", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prorrogas_payments_options_period_id"),
        "prorrogas_payments_options", ["period_id"], unique=False,
    )

    # Avisos propios de la app. NO es `core_notifications`: esta tabla es un
    # buzón interno de prórrogas y no pasa por NotificationService.
    op.create_table(
        "prorrogas_notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["period_id"], ["core_academic_periods.id"],
            onupdate="CASCADE", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["core_users.id"],
            onupdate="CASCADE", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prorrogas_notifications_period_id"),
        "prorrogas_notifications", ["period_id"], unique=False,
    )

    op.create_table(
        "prorrogas_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("total_amount_id", sa.BigInteger(), nullable=False),
        sa.Column("letter", sa.Text(), nullable=True),
        sa.Column("payments_terms", sa.Integer(), nullable=False),
        sa.Column("status", _REQUEST_STATUS, server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["period_id"], ["core_academic_periods.id"],
            onupdate="CASCADE", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"], ["core_programs.id"],
            onupdate="CASCADE", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["core_users.id"],
            onupdate="CASCADE", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["total_amount_id"], ["prorrogas_payments_options.id"],
            onupdate="CASCADE", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prorrogas_requests_period_id"),
        "prorrogas_requests", ["period_id"], unique=False,
    )

    op.create_table(
        "prorrogas_payments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("num_payments_terms", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("expiration_date", sa.DateTime(), nullable=True),
        sa.Column("payday", sa.DateTime(), nullable=True),
        sa.Column("status", _PAYMENT_STATUS, nullable=False),
        sa.Column("admin_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["period_id"], ["core_academic_periods.id"],
            onupdate="CASCADE", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["prorrogas_requests.id"],
            onupdate="CASCADE", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prorrogas_payments_period_id"),
        "prorrogas_payments", ["period_id"], unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_prorrogas_payments_period_id"), table_name="prorrogas_payments")
    op.drop_table("prorrogas_payments")
    op.drop_index(op.f("ix_prorrogas_requests_period_id"), table_name="prorrogas_requests")
    op.drop_table("prorrogas_requests")
    op.drop_index(
        op.f("ix_prorrogas_notifications_period_id"), table_name="prorrogas_notifications"
    )
    op.drop_table("prorrogas_notifications")
    op.drop_index(
        op.f("ix_prorrogas_payments_options_period_id"),
        table_name="prorrogas_payments_options",
    )
    op.drop_table("prorrogas_payments_options")
    op.drop_table("prorrogas_period_config")

    # Los tipos se sueltan al final: mientras exista una columna que los use,
    # el DROP TYPE falla.
    bind = op.get_bind()
    _PAYMENT_STATUS.drop(bind, checkfirst=True)
    _REQUEST_STATUS.drop(bind, checkfirst=True)
