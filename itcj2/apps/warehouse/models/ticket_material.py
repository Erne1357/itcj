from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class WarehouseTicketMaterial(Base):
    """
    Resumen de material consumido por ticket.

    Relación polimórfica: source_app + source_ticket_id identifican
    al ticket en la app de origen (helpdesk o maint).

    La integridad referencial se mantiene a nivel de aplicación
    (el FifoService valida que el ticket exista antes de crear el registro).
    """

    __tablename__ = "warehouse_ticket_materials"

    id = Column(Integer, primary_key=True)
    source_app = Column(String(30), nullable=False)      # 'helpdesk' | 'maint'
    source_ticket_id = Column(Integer, nullable=False)   # ID del ticket en su app
    product_id = Column(
        Integer, ForeignKey("warehouse_products.id"), nullable=False
    )
    quantity_used = Column(Numeric(10, 2), nullable=False)
    added_by_id = Column(
        BigInteger, ForeignKey("core_users.id"), nullable=False
    )
    added_at = Column(DateTime, nullable=False, server_default=func.now())
    notes = Column(Text, nullable=True)

    product = relationship("WarehouseProduct", back_populates="ticket_materials")
    added_by = relationship("User", foreign_keys=[added_by_id])

    __table_args__ = (
        UniqueConstraint(
            "source_app", "source_ticket_id", "product_id",
            name="uq_warehouse_ticket_materials",
        ),
        Index(
            "ix_warehouse_ticket_materials_source",
            "source_app", "source_ticket_id",
        ),
        Index("ix_warehouse_ticket_materials_product", "product_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<WarehouseTicketMaterial {self.id}: "
            f"{self.source_app}#{self.source_ticket_id} product={self.product_id}>"
        )
