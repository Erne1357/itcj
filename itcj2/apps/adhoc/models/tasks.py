"""
Tareas colgadas de una incidencia, evento de programa o documento.

`AdhocTask` es polimórfica por 3 FK nullable mutuamente excluyentes
(`incident_id`/`program_id`/`document_id`) — ahora garantizado por
CheckConstraint (el legacy no tenía ninguno y asumía prioridad
`program > incident > document` en Python). `flow_step` es el relationship
que el legacy no tenía.

`adhoc_task_assignees` **no** lleva `is_completed` (columna muerta en el
legacy: 0 lecturas/escrituras en todo `routes/`, `services/`, `static/js/`).

`AdhocTaskApproval` es tabla NUEVA (arregla el bug #4 del legacy: la
aprobación multi-validador se modelaba removiendo al usuario de
`assigned_users`, perdiendo para siempre el registro de quién estaba
asignado y quién aprobó).
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class AdhocTask(Base):
    __tablename__ = "adhoc_tasks"

    id = Column(Integer, primary_key=True)
    description = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, server_default=text("'Pendiente'"))
    priority = Column(String(20), nullable=False, server_default=text("'Media'"))
    start_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    #: Origen en el legacy, prefijado porque las tareas vienen de TRES tablas
    #: cuyos espacios de id se solapan: ``t:{tareas.task_id}``,
    #: ``tp:{tareas_prog.task_id}``, ``ip:{indiceprin.accion_id}``.
    legacy_id = Column(String(30), nullable=True, unique=True)

    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)
    incident_id = Column(Integer, ForeignKey("adhoc_incidents.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    program_id = Column(Integer, ForeignKey("adhoc_program_events.id", ondelete="CASCADE"),
                         nullable=True, index=True)
    document_id = Column(Integer, ForeignKey("adhoc_documents.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    flow_step_id = Column(Integer, ForeignKey("adhoc_approval_flow_steps.id"),
                           nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    created_by = relationship("User", foreign_keys=[created_by_id])
    incident = relationship("AdhocIncident", foreign_keys=[incident_id])
    program = relationship("AdhocProgramEvent", foreign_keys=[program_id])
    document = relationship("AdhocDocument", foreign_keys=[document_id])
    flow_step = relationship("AdhocApprovalFlowStep", foreign_keys=[flow_step_id])
    assignees = relationship("User", secondary="adhoc_task_assignees")
    comments = relationship("AdhocTaskComment", back_populates="task", cascade="all, delete-orphan")
    approvals = relationship("AdhocTaskApproval", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pendiente','En Proceso','En Revisión','En Espera','Completada','Rechazada')",
            name="ck_adhoc_tasks_status",
        ),
        CheckConstraint(
            "priority IN ('Baja','Media','Alta','Urgente')",
            name="ck_adhoc_tasks_priority",
        ),
        CheckConstraint(
            "(incident_id IS NOT NULL)::int + (program_id IS NOT NULL)::int "
            "+ (document_id IS NOT NULL)::int = 1",
            name="ck_adhoc_tasks_single_parent",
        ),
    )

    def __repr__(self) -> str:
        return f"<AdhocTask {self.id}: {self.description[:30]}>"


adhoc_task_assignees = Table(
    "adhoc_task_assignees",
    Base.metadata,
    Column("task_id", Integer, ForeignKey("adhoc_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True),
    Column("notified_overdue", Boolean, nullable=False, server_default=text("false")),
    Index("ix_adhoc_task_assignees_user_id", "user_id"),
)


class AdhocTaskComment(Base):
    __tablename__ = "adhoc_task_comments"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("adhoc_tasks.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)
    comment = Column(Text, nullable=False)
    file_path = Column(String(255), nullable=True)   # ruta relativa "{task_id}/{filename}"
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("AdhocTask", back_populates="comments")
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<AdhocTaskComment task={self.task_id} user={self.user_id}>"


class AdhocTaskCommentFile(Base):
    """Adjuntos de un comentario de tarea.

    ``AdhocTaskComment.file_path`` solo admite UN archivo por comentario, y el
    legacy tiene 85 comentarios con más de uno (uno llega a 14). La columna
    vieja se conserva para no romper el flujo de subida actual; lo nuevo y lo
    migrado va aquí.

    ``file_path`` nullable por la misma razón que en
    :class:`AdhocIncidentFile`: hay registros cuyo binario ya no existe.
    """
    __tablename__ = "adhoc_task_comment_files"

    id = Column(Integer, primary_key=True)
    task_comment_id = Column(Integer, ForeignKey("adhoc_task_comments.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    file_path = Column(String(255), nullable=True)   # ruta relativa "{task_id}/{filename}"
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    comment = relationship("AdhocTaskComment", foreign_keys=[task_comment_id])
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    def __repr__(self) -> str:
        return f"<AdhocTaskCommentFile {self.original_name} (comment={self.task_comment_id})>"


class AdhocTaskApproval(Base):
    __tablename__ = "adhoc_task_approvals"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("adhoc_tasks.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)
    decision = Column(String(20), nullable=False)
    comment_id = Column(Integer, ForeignKey("adhoc_task_comments.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("AdhocTask", back_populates="approvals")
    user = relationship("User", foreign_keys=[user_id])
    comment = relationship("AdhocTaskComment", foreign_keys=[comment_id])

    __table_args__ = (
        CheckConstraint("decision IN ('aprobado','rechazado')", name="ck_adhoc_task_approvals_decision"),
        UniqueConstraint("task_id", "user_id", name="uq_adhoc_task_approvals_task_user"),
    )

    def __repr__(self) -> str:
        return f"<AdhocTaskApproval task={self.task_id} user={self.user_id} {self.decision}>"
