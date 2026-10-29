"""titulatec fase 4: sinodales (perfil docente, carrera->depto, historial)

Escrita a mano. Spec: docs/superpowers/specs/2026-10-21-titulatec-fase4-sinodales-design.md §5.2

Que agrega
----------
- `titulatec_teacher_profiles`, `titulatec_program_departments`,
  `titulatec_department_settings`.
- `titulatec_synodal_assignments`: `is_active`, `replaced_at`, `replaced_by_id`,
  `replacement_reason`; quita `uq_titulatec_synodal_process_user` y crea los
  indices unicos parciales `uq_titulatec_synodal_active_role` y
  `uq_titulatec_synodal_active_user` (WHERE is_active).
- `titulatec_modalities.option_label`.

Downgrade (CON PERDIDA): borra las tres tablas y las columnas nuevas. El
UNIQUE(process_id, user_id) no admite el historial, asi que el downgrade
elimina antes las filas sustituidas (is_active = false).

Revision ID: tt20261022a
Revises: tt20261021a
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261022a"
down_revision = "tt20261021a"
branch_labels = None
depends_on = None

_SYN = "titulatec_synodal_assignments"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_table(
        "titulatec_teacher_profiles",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), primary_key=True),
        sa.Column("academic_degree", sa.String(150), nullable=False),
        sa.Column("professional_license", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True),
    )
    op.create_table(
        "titulatec_program_departments",
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("core_programs.id"), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("core_departments.id"), nullable=False),
        sa.Column("official_name", sa.String(200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True),
    )
    op.create_index("ix_titulatec_program_departments_department_id",
                    "titulatec_program_departments", ["department_id"])
    op.create_table(
        "titulatec_department_settings",
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("core_departments.id"), primary_key=True),
        sa.Column("oficio_header", sa.String(200), nullable=False),
        sa.Column("addressee_position_code", sa.String(60), nullable=False),
        sa.Column("attn_position_code", sa.String(60), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True),
    )

    op.add_column(_SYN, sa.Column("is_active", sa.Boolean(), nullable=False,
                                  server_default=sa.text("true")))
    op.add_column(_SYN, sa.Column("replaced_at", sa.DateTime(), nullable=True))
    op.add_column(_SYN, sa.Column("replaced_by_id", sa.BigInteger(), nullable=True))
    op.add_column(_SYN, sa.Column("replacement_reason", sa.Text(), nullable=True))
    op.create_foreign_key("titulatec_synodal_assignments_replaced_by_id_fkey", _SYN,
                          "core_users", ["replaced_by_id"], ["id"])
    op.create_index("ix_titulatec_synodal_assignments_is_active", _SYN, ["is_active"])
    op.drop_constraint("uq_titulatec_synodal_process_user", _SYN, type_="unique")
    op.create_index("uq_titulatec_synodal_active_role", _SYN, ["process_id", "role"],
                    unique=True, postgresql_where=sa.text("is_active"))
    op.create_index("uq_titulatec_synodal_active_user", _SYN, ["process_id", "user_id"],
                    unique=True, postgresql_where=sa.text("is_active"))

    op.add_column("titulatec_modalities", sa.Column("option_label", sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column("titulatec_modalities", "option_label")

    op.drop_index("uq_titulatec_synodal_active_user", table_name=_SYN)
    op.drop_index("uq_titulatec_synodal_active_role", table_name=_SYN)
    # El UNIQUE(process_id, user_id) no admite el historial: se descartan las sustituidas.
    op.execute(f"DELETE FROM {_SYN} WHERE is_active = false")
    op.create_unique_constraint("uq_titulatec_synodal_process_user", _SYN,
                                ["process_id", "user_id"])
    op.drop_index("ix_titulatec_synodal_assignments_is_active", table_name=_SYN)
    op.drop_constraint("titulatec_synodal_assignments_replaced_by_id_fkey", _SYN, type_="foreignkey")
    op.drop_column(_SYN, "replacement_reason")
    op.drop_column(_SYN, "replaced_by_id")
    op.drop_column(_SYN, "replaced_at")
    op.drop_column(_SYN, "is_active")

    op.drop_table("titulatec_department_settings")
    op.drop_index("ix_titulatec_program_departments_department_id",
                  table_name="titulatec_program_departments")
    op.drop_table("titulatec_program_departments")
    op.drop_table("titulatec_teacher_profiles")
