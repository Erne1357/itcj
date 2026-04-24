"""
Modelo para solicitudes de baja de equipos de inventario.
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryRetirementRequest(Base):
    """
    Solicitud formal de baja de uno o más equipos.
    Flujo: DRAFT → PENDING → AWAITING_RECURSOS_MATERIALES → AWAITING_SUBDIRECTOR → AWAITING_DIRECTOR → APPROVED | REJECTED
           DRAFT | PENDING → CANCELLED
    """
    __tablename__ = "helpdesk_inventory_retirement_requests"

    id = Column(Integer, primary_key=True)

    folio = Column(String(20), unique=True, nullable=False, index=True)
    # Formato: BAJA-{YEAR}-{SEQ:03d}  ej: BAJA-2026-001

    status = Column(String(20), nullable=False, default='DRAFT', index=True)
    # DRAFT | PENDING | AWAITING_RECURSOS_MATERIALES | AWAITING_SUBDIRECTOR | AWAITING_DIRECTOR | APPROVED | REJECTED | CANCELLED

    reason = Column(Text, nullable=False)

    oficio_data = Column(JSON, nullable=True)
    # Guarda: notas adicionales, ubicación override, causa oficializada

    requested_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)
    reviewed_by_id  = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    reviewed_at     = Column(DateTime, nullable=True)
    review_notes    = Column(Text, nullable=True)

    # Documento adjunto (PDF/DOCX subido por el solicitante)
    document_path          = Column(String(500), nullable=True)
    document_original_name = Column(String(255), nullable=True)

    # Cuándo se generó el formato PDF interno
    format_generated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    reviewed_by  = relationship("User", foreign_keys=[reviewed_by_id])

    items = relationship(
        "InventoryRetirementRequestItem",
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def to_dict(self, include_items=False):
        data = {
            "id":           self.id,
            "folio":        self.folio,
            "status":       self.status,
            "reason":       self.reason,
            "oficio_data":  self.oficio_data,
            "requested_by": {
                "id":        self.requested_by.id,
                "full_name": self.requested_by.full_name,
            } if self.requested_by else None,
            "reviewed_by": {
                "id":        self.reviewed_by.id,
                "full_name": self.reviewed_by.full_name,
            } if self.reviewed_by else None,
            "reviewed_at":              self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes":             self.review_notes,
            "document_path":            self.document_path,
            "document_original_name":   self.document_original_name,
            "format_generated_at":      self.format_generated_at.isoformat() if self.format_generated_at else None,
            "created_at":               self.created_at.isoformat() if self.created_at else None,
            "updated_at":               self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            data["items"] = [ri.to_dict() for ri in self.items]
        return data


class InventoryRetirementRequestItem(Base):
    """Equipos incluidos en una solicitud de baja."""
    __tablename__ = "helpdesk_inventory_retirement_request_items"

    id         = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("helpdesk_inventory_retirement_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id    = Column(Integer, ForeignKey("helpdesk_inventory_items.id"), nullable=False, index=True)
    item_notes = Column(Text, nullable=True)

    valor_unitario = Column(Numeric(12, 2), nullable=True)
    desalojo       = Column(Boolean, default=False, nullable=False)
    bodega         = Column(Boolean, default=False, nullable=False)
    afectacion     = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", "item_id", name="uq_retirement_request_item"),
    )

    request        = relationship("InventoryRetirementRequest", back_populates="items")
    inventory_item = relationship("InventoryItem")

    def to_dict(self):
        return {
            "id":             self.id,
            "request_id":     self.request_id,
            "item_id":        self.item_id,
            "item_notes":     self.item_notes,
            "valor_unitario": float(self.valor_unitario) if self.valor_unitario is not None else None,
            "desalojo":       self.desalojo,
            "bodega":         self.bodega,
            "afectacion":     self.afectacion,
            "item":           self.inventory_item.to_dict(include_relations=True) if self.inventory_item else None,
        }


class InventoryRetirementSignature(Base):
    """Firma de aprobación de una etapa del flujo multi-firma de baja."""
    __tablename__ = "helpdesk_inventory_retirement_signatures"

    id         = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("helpdesk_inventory_retirement_requests.id", ondelete="CASCADE"), nullable=False, index=True)

    step           = Column(Integer, nullable=False)         # 1=jefe rec mat, 2=subdirector, 3=director
    position_code  = Column(String(50), nullable=False)      # 'head_mat_services', 'secretary_sub_admin_services', 'director'
    position_title = Column(String(120), nullable=False)     # título a mostrar en el oficio

    signed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    signed_at    = Column(DateTime, nullable=True)
    action       = Column(String(10), nullable=True)         # 'APPROVED' | 'REJECTED'
    notes        = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    request   = relationship("InventoryRetirementRequest", backref="signatures")
    signed_by = relationship("User", foreign_keys=[signed_by_id])
