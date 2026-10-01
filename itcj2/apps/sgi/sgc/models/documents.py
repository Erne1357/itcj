"""
Documentos de Calidad con flujo de aprobación multi-paso y multi-validador.

`SgcApprovalFlowStep.flow_id` es NOT NULL (el legacy lo tenía nullable: un
paso sin flujo es basura). `SgcDocument.approval_date` es `DateTime` (el
legacy la declaraba `Date` pero le asignaba un `datetime` completo vía
`utcnow`).
`SgcDocument.current_step` es el relationship que el legacy no tenía —
resolvía `FlowStep.query.get(doc.current_step_id)` a mano.

Nota de integridad referencial (ver `document_flow_service` en F3/F7):
`current_step_id` (en esta tabla) y `flow_step_id` (en `sgc_tasks`) son FK
**sin `ondelete`** a propósito (RESTRICT) — borrar un paso con documentos o
tareas activas debe fallar con un error claro, no dejar columnas huérfanas.
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class SgcDocumentCategory(Base):
    __tablename__ = "sgc_document_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SgcDocumentCategory {self.name}>"


class SgcDocumentClassification(Base):
    __tablename__ = "sgc_document_classifications"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SgcDocumentClassification {self.name}>"


class SgcApprovalFlow(Base):
    __tablename__ = "sgc_approval_flows"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    #: `rutas_apro.ruta_id` del legacy. Idempotencia del ETL.
    legacy_id = Column(Integer, nullable=True, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    steps = relationship(
        "SgcApprovalFlowStep", back_populates="flow",
        cascade="all, delete-orphan", order_by="SgcApprovalFlowStep.step_order",
    )

    def __repr__(self) -> str:
        return f"<SgcApprovalFlow {self.name}>"


class SgcApprovalFlowStep(Base):
    __tablename__ = "sgc_approval_flow_steps"

    id = Column(Integer, primary_key=True)
    flow_id = Column(Integer, ForeignKey("sgc_approval_flows.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    name = Column(String(100), nullable=False)
    days_limit = Column(Integer, nullable=False, server_default=text("3"))
    step_order = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    flow = relationship("SgcApprovalFlow", back_populates="steps")
    assignees = relationship("User", secondary="sgc_flow_step_assignees")

    __table_args__ = (
        UniqueConstraint("flow_id", "step_order", name="uq_sgc_approval_flow_steps_flow_order"),
    )

    def __repr__(self) -> str:
        return f"<SgcApprovalFlowStep {self.name} (flow={self.flow_id})>"


sgc_flow_step_assignees = Table(
    "sgc_flow_step_assignees",
    Base.metadata,
    Column("step_id", Integer, ForeignKey("sgc_approval_flow_steps.id", ondelete="CASCADE"),
           primary_key=True),
    Column("user_id", BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True),
    Column("notify_on_overdue", Boolean, nullable=False, server_default=text("false")),
    Index("ix_sgc_flow_step_assignees_user_id", "user_id"),
)


class SgcDocument(Base):
    __tablename__ = "sgc_documents"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    version = Column(String(10), nullable=False, server_default=text("'1.0'"))
    status = Column(String(50), nullable=False, server_default=text("'Borrador'"))
    notes = Column(Text, nullable=True)
    approval_date = Column(DateTime, nullable=True)
    file_url = Column(String(255), nullable=True)   # ruta relativa "{document_id}/{filename}"

    #: Vencimiento del documento controlado. En un SGC ISO 9001 el control de
    #: documentos vencidos es el punto del sistema; el legacy lo guardaba en
    #: `dap_vigencia` (199 de 206 poblados, 49 ya vencidos).
    expiration_date = Column(Date, nullable=True)

    #: Raíz de la cadena de versiones. NULL = este documento ES la raíz.
    #: Sin `ondelete` a propósito (RESTRICT), por la misma razón que
    #: `current_step_id`: borrar la raíz de una cadena con versiones colgando
    #: debe fallar con un error claro, no dejar huérfanos.
    parent_id = Column(Integer, ForeignKey("sgc_documents.id"), nullable=True, index=True)
    #: Punta de la cadena. La lista de documentos filtra por esto para no
    #: mostrar las versiones superadas mezcladas con las vigentes.
    is_current = Column(Boolean, nullable=False, server_default=text("true"), index=True)

    #: `doc_approve.dap_id` del legacy. Da idempotencia al ETL y trazabilidad
    #: hacia atrás. NULL en todo lo capturado en el sistema nuevo.
    legacy_id = Column(Integer, nullable=True, unique=True)

    category_id = Column(Integer, ForeignKey("sgc_document_categories.id"), nullable=True, index=True)
    area_id = Column(Integer, ForeignKey("sgc_areas.id"), nullable=True, index=True)
    process_id = Column(Integer, ForeignKey("sgc_processes.id"), nullable=True, index=True)
    classification_id = Column(Integer, ForeignKey("sgc_document_classifications.id"),
                                nullable=True, index=True)
    flow_id = Column(Integer, ForeignKey("sgc_approval_flows.id"), nullable=True, index=True)
    current_step_id = Column(Integer, ForeignKey("sgc_approval_flow_steps.id"),
                              nullable=True, index=True)
    author_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("SgcDocumentCategory")
    area = relationship("SgcArea")
    process = relationship("SgcProcess")
    classification = relationship("SgcDocumentClassification")
    flow = relationship("SgcApprovalFlow")
    current_step = relationship("SgcApprovalFlowStep", foreign_keys=[current_step_id])
    author = relationship("User", foreign_keys=[author_id])
    parent = relationship("SgcDocument", remote_side=[id], foreign_keys=[parent_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('Borrador','En Revisión','Aprobado','Rechazado','Obsoleto')",
            name="ck_sgc_documents_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<SgcDocument {self.code or self.id}: {self.title}>"


class SgcDocumentAcknowledgement(Base):
    """Acuse de recibo de un documento controlado: evidencia ISO de difusión.

    Solo entra aquí lo que de verdad es un acuse. El legacy tenía dos cosas
    parecidas y solo una lo era: las acciones de difusión de ``indiceprin``
    (con fecha real de acuse) sí, y ``ver_doctos`` no — esa resultó ser una
    lista de visibilidad, ver :class:`SgcDocumentVisibility`.

    Por eso ``acknowledged_at`` es NOT NULL: todas las filas migradas traen su
    fecha. Una tabla de acuses con fechas vacías no sostiene una auditoría.
    """
    __tablename__ = "sgc_document_acknowledgements"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("sgc_documents.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    acknowledged_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    document = relationship("SgcDocument", foreign_keys=[document_id])
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("document_id", "user_id",
                          name="uq_sgc_document_acknowledgements_document_user"),
    )

    def __repr__(self) -> str:
        return f"<SgcDocumentAcknowledgement doc={self.document_id} user={self.user_id}>"


class SgcDocumentVisibility(Base):
    """Quién puede ver qué documento controlado.

    Es el destino honesto de ``ver_doctos`` del legacy, que el análisis inicial
    confundió con acuses de lectura. La forma de los datos lo desmiente: 126
    documentos tienen exactamente los mismos 51 usuarios, la mediana es 47 de 63
    usuarios totales y 33 personas aparecen en más de 600 de los 742 documentos.
    Eso es la plantilla completa asignada por documento, no gente leyendo — y la
    vista del propio proveedor se llamaba ``UsuariosxDocumento``.

    No tiene fecha porque el origen no la tiene (``ver_doctos`` son tres
    columnas: id, documento, usuario).
    """
    __tablename__ = "sgc_document_visibility"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("sgc_documents.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    document = relationship("SgcDocument", foreign_keys=[document_id])
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("document_id", "user_id",
                          name="uq_sgc_document_visibility_document_user"),
    )

    def __repr__(self) -> str:
        return f"<SgcDocumentVisibility doc={self.document_id} user={self.user_id}>"
