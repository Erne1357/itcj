"""titulatec fase 5: revision de sinodales (versiones, votos, recordatorios, chat, dias inhabiles)

Escrita a mano. Spec: docs/superpowers/specs/2026-10-22-titulatec-fase5-revision-sinodales-design.md §5

Que agrega
----------
- `titulatec_review_versions`, `titulatec_review_votes`, `titulatec_review_reminders`,
  `titulatec_non_working_days` y `titulatec_chat_reads`.
- `titulatec_chats.closed_at`.
- `titulatec_chat_messages`: `author_id` pasa a NULL-able (mensajes del sistema),
  `kind` (NOT NULL, default 'message'), `version_id` (FK a las versiones),
  `attachment_mime`, `attachment_size` e indice `(chat_id, id)`.

Downgrade (CON PERDIDA): borra las cinco tablas nuevas y las columnas nuevas.
Antes de devolver `author_id` a NOT NULL borra los mensajes sin autor (los del
sistema), desligando primero las respuestas (`parent_id`) que los citan.

Revision ID: tt20261022c
Revises: tt20261022b
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261022c"
down_revision = "tt20261022b"
branch_labels = None
depends_on = None

_MSG = "titulatec_chat_messages"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.create_table(
        "titulatec_review_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("titulatec_processes.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(255), nullable=True),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("process_id", "number",
                            name="uq_titulatec_review_versions_process_number"),
    )
    op.create_index("ix_titulatec_review_versions_process_id",
                    "titulatec_review_versions", ["process_id"])

    op.create_table(
        "titulatec_review_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("titulatec_review_versions.id"),
                  nullable=False),
        sa.Column("assignment_id", sa.Integer(),
                  sa.ForeignKey("titulatec_synodal_assignments.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("version_id", "assignment_id",
                            name="uq_titulatec_review_votes_version_assignment"),
        sa.CheckConstraint("verdict IN ('approved', 'changes_requested')",
                           name="ck_titulatec_review_votes_verdict"),
    )
    op.create_index("ix_titulatec_review_votes_version_id",
                    "titulatec_review_votes", ["version_id"])

    op.create_table(
        "titulatec_review_reminders",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("titulatec_review_versions.id"),
                  primary_key=True),
        sa.Column("assignment_id", sa.Integer(),
                  sa.ForeignKey("titulatec_synodal_assignments.id"), primary_key=True),
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "titulatec_non_working_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False, unique=True),
        sa.Column("description", sa.String(150), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "titulatec_chat_reads",
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("titulatec_chats.id"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("core_users.id"), primary_key=True),
        sa.Column("last_read_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.add_column("titulatec_chats", sa.Column("closed_at", sa.DateTime(), nullable=True))

    op.alter_column(_MSG, "author_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column(_MSG, sa.Column("kind", sa.String(20), nullable=False,
                                  server_default=sa.text("'message'")))
    op.add_column(_MSG, sa.Column("version_id", sa.Integer(), nullable=True))
    op.add_column(_MSG, sa.Column("attachment_mime", sa.String(100), nullable=True))
    op.add_column(_MSG, sa.Column("attachment_size", sa.Integer(), nullable=True))
    op.create_foreign_key("titulatec_chat_messages_version_id_fkey", _MSG,
                          "titulatec_review_versions", ["version_id"], ["id"])
    op.create_index("ix_titulatec_chat_messages_version_id", _MSG, ["version_id"])
    op.create_index("ix_titulatec_chat_messages_chat_id_id", _MSG, ["chat_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_titulatec_chat_messages_chat_id_id", table_name=_MSG)
    op.drop_index("ix_titulatec_chat_messages_version_id", table_name=_MSG)
    op.drop_constraint("titulatec_chat_messages_version_id_fkey", _MSG, type_="foreignkey")
    op.drop_column(_MSG, "attachment_size")
    op.drop_column(_MSG, "attachment_mime")
    op.drop_column(_MSG, "version_id")
    op.drop_column(_MSG, "kind")

    # Los mensajes del sistema (sin autor) no caben en el esquema viejo: se
    # desligan las respuestas que los citan y se borran.
    op.execute(
        f"UPDATE {_MSG} SET parent_id = NULL "
        f"WHERE parent_id IN (SELECT id FROM {_MSG} WHERE author_id IS NULL)"
    )
    op.execute(f"DELETE FROM {_MSG} WHERE author_id IS NULL")
    op.alter_column(_MSG, "author_id", existing_type=sa.BigInteger(), nullable=False)

    op.drop_column("titulatec_chats", "closed_at")

    op.drop_table("titulatec_chat_reads")
    op.drop_table("titulatec_non_working_days")
    op.drop_table("titulatec_review_reminders")
    op.drop_index("ix_titulatec_review_votes_version_id", table_name="titulatec_review_votes")
    op.drop_table("titulatec_review_votes")
    op.drop_index("ix_titulatec_review_versions_process_id", table_name="titulatec_review_versions")
    op.drop_table("titulatec_review_versions")
