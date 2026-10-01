"""sgc: acuses, visibilidad, archivos de incidencia y comentario, versiones de documento

Soporta la migración del SGC legacy (`ControlDocumental`, SQL Server del proveedor
`calidad.com.mx`) a `itcj2/apps/sgi/sgc`. Cuatro tablas nuevas y once columnas.

Escrita a mano a propósito. `--autogenerate` arrastró drift preexistente de todo el
repo (índices renombrados de helpdesk y core, constraints de nombre distinto) que no
tiene nada que ver con este cambio y que aplicar sería destructivo. Aquí solo va lo de
sgc. Además autogenerate NO detecta cambios de CheckConstraint, así que el nuevo
estado 'Obsoleto' se aplica explícitamente abajo.

Qué entra y por qué:

- `sgc_document_acknowledgements` — acuse de recibo de documento controlado, la
  evidencia ISO de difusión. `acknowledged_at` es NOT NULL porque solo se migra lo que
  trae fecha real (`indiceprin.a_done_date`).
- `sgc_document_visibility` — quién puede ver qué documento. Es `ver_doctos` del
  legacy, que el análisis inicial confundió con acuses: 126 documentos tienen los
  mismos 51 usuarios y 33 personas aparecen en más de 600 de 742 documentos, o sea es
  una plantilla de visibilidad, no gente leyendo.
- `sgc_incident_files` / `sgc_task_comment_files` — adjuntos que el esquema no
  soportaba (409 de incidencia; y 85 comentarios del legacy tienen más de un archivo,
  uno llega a 14). `file_path` nullable: 51 adjuntos existen como registro pero su
  binario ya no está en el servidor del proveedor.
- `sgc_documents.parent_id` + `is_current` — cadena de versiones (148 cadenas en el
  legacy). `parent_id` sin `ondelete` (RESTRICT), igual que `current_step_id`.
- `sgc_documents.expiration_date` — vigencia del documento (199 de 206 poblados en el
  legacy, 49 ya vencidos). En ISO 9001 el control de documentos vencidos es el punto.
- `legacy_id` en 8 tablas — idempotencia del ETL y trazabilidad hacia el legacy.
- `sgc_program_event_files.file_path` pasa a nullable, por el mismo motivo que las
  tablas de archivos nuevas.
- `ck_sgc_documents_status` gana 'Obsoleto': 59 de los 206 documentos del legacy son
  versiones superadas (`dap_approval_status = 2`) y sin ese valor entrarían como
  'Aprobado', indistinguibles de los vigentes.

Revision ID: b9b4d846ec2d
Revises: 23004eb05186
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa


revision = "b9b4d846ec2d"
down_revision = "23004eb05186"
branch_labels = None
depends_on = None


#: Tablas que reciben `legacy_id INTEGER UNIQUE`.
_LEGACY_ID_TABLES = (
    "sgc_areas",
    "sgc_processes",
    "sgc_approval_flows",
    "sgc_documents",
    "sgc_incidents",
    "sgc_program_events",
    "sgc_indicators",
)

_STATUS_CK = "ck_sgc_documents_status"
_STATUS_OLD = "status IN ('Borrador','En Revisión','Aprobado','Rechazado')"
_STATUS_NEW = "status IN ('Borrador','En Revisión','Aprobado','Rechazado','Obsoleto')"


def upgrade() -> None:
    # ---------------------------------------------------------------- tablas
    op.create_table(
        "sgc_document_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["sgc_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "user_id",
                            name="uq_sgc_document_acknowledgements_document_user"),
    )
    op.create_index("ix_sgc_document_acknowledgements_document_id",
                    "sgc_document_acknowledgements", ["document_id"])
    op.create_index("ix_sgc_document_acknowledgements_user_id",
                    "sgc_document_acknowledgements", ["user_id"])

    op.create_table(
        "sgc_document_visibility",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["sgc_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["core_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "user_id",
                            name="uq_sgc_document_visibility_document_user"),
    )
    op.create_index("ix_sgc_document_visibility_document_id",
                    "sgc_document_visibility", ["document_id"])
    op.create_index("ix_sgc_document_visibility_user_id",
                    "sgc_document_visibility", ["user_id"])

    op.create_table(
        "sgc_incident_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["sgc_incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sgc_incident_files_incident_id",
                    "sgc_incident_files", ["incident_id"])
    op.create_index("ix_sgc_incident_files_uploaded_by_id",
                    "sgc_incident_files", ["uploaded_by_id"])

    op.create_table(
        "sgc_task_comment_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_comment_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_comment_id"], ["sgc_task_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sgc_task_comment_files_task_comment_id",
                    "sgc_task_comment_files", ["task_comment_id"])
    op.create_index("ix_sgc_task_comment_files_uploaded_by_id",
                    "sgc_task_comment_files", ["uploaded_by_id"])

    # ------------------------------------------------- columnas de documento
    op.add_column("sgc_documents", sa.Column("expiration_date", sa.Date(), nullable=True))
    op.add_column("sgc_documents", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.add_column(
        "sgc_documents",
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_index("ix_sgc_documents_parent_id", "sgc_documents", ["parent_id"])
    op.create_index("ix_sgc_documents_is_current", "sgc_documents", ["is_current"])
    # Sin ondelete: borrar la raíz de una cadena con versiones colgando debe fallar.
    op.create_foreign_key(
        "fk_sgc_documents_parent_id", "sgc_documents", "sgc_documents",
        ["parent_id"], ["id"],
    )

    # ------------------------------------------------------------ legacy_id
    for table in _LEGACY_ID_TABLES:
        op.add_column(table, sa.Column("legacy_id", sa.Integer(), nullable=True))
        op.create_unique_constraint(f"uq_{table}_legacy_id", table, ["legacy_id"])

    # `sgc_tasks.legacy_id` es texto: las tareas vienen de tres tablas legacy cuyos
    # espacios de id se solapan (t:/tp:/ip:).
    op.add_column("sgc_tasks", sa.Column("legacy_id", sa.String(length=30), nullable=True))
    op.create_unique_constraint("uq_sgc_tasks_legacy_id", "sgc_tasks", ["legacy_id"])

    # ------------------------------------------- adjuntos de evento nullable
    op.alter_column("sgc_program_event_files", "file_path",
                    existing_type=sa.String(length=255), nullable=True)

    # --------------------------------------------------- estado 'Obsoleto'
    op.drop_constraint(_STATUS_CK, "sgc_documents", type_="check")
    op.create_check_constraint(_STATUS_CK, "sgc_documents", _STATUS_NEW)


def downgrade() -> None:
    # Los documentos 'Obsoleto' vuelven a 'Aprobado' antes de reponer el CHECK viejo:
    # si no, el constraint no se puede recrear sobre datos que ya lo violan.
    op.execute(
        "UPDATE sgc_documents SET status = 'Aprobado' WHERE status = 'Obsoleto'"
    )
    op.drop_constraint(_STATUS_CK, "sgc_documents", type_="check")
    op.create_check_constraint(_STATUS_CK, "sgc_documents", _STATUS_OLD)

    op.alter_column("sgc_program_event_files", "file_path",
                    existing_type=sa.String(length=255), nullable=False)

    op.drop_constraint("uq_sgc_tasks_legacy_id", "sgc_tasks", type_="unique")
    op.drop_column("sgc_tasks", "legacy_id")
    for table in reversed(_LEGACY_ID_TABLES):
        op.drop_constraint(f"uq_{table}_legacy_id", table, type_="unique")
        op.drop_column(table, "legacy_id")

    op.drop_constraint("fk_sgc_documents_parent_id", "sgc_documents", type_="foreignkey")
    op.drop_index("ix_sgc_documents_is_current", table_name="sgc_documents")
    op.drop_index("ix_sgc_documents_parent_id", table_name="sgc_documents")
    op.drop_column("sgc_documents", "is_current")
    op.drop_column("sgc_documents", "parent_id")
    op.drop_column("sgc_documents", "expiration_date")

    op.drop_table("sgc_task_comment_files")
    op.drop_table("sgc_incident_files")
    op.drop_table("sgc_document_visibility")
    op.drop_table("sgc_document_acknowledgements")
