from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base

# Tipos válidos de movimiento
MOVEMENT_TYPES = frozenset({
    "ENTRY",        # Nueva entrada de stock (compra)
    "CONSUMED",     # Consumo FIFO desde un ticket
    "ADJUSTED_IN",  # Ajuste positivo (corrección)
    "ADJUSTED_OUT", # Ajuste negativo (desecho, pérdida)
    "RETURNED",     # Devolución (reversión de consumo)
    "VOIDED",       # Anulación de un lote completo
})


class WarehouseMovement(Base):
    """
    Registro de cada operación de stock — trazabilidad completa.

    La relación con tickets es polimórfica: source_app + source_ticket_id
    en lugar de FKs nullable a múltiples tablas.
    """

    __tablename__ = "warehouse_movements"

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer, ForeignKey("warehouse_products.id"), nullable=False
    )
    entry_id = Column(
        Integer, ForeignKey("warehouse_stock_entries.id"), nullable=True
    )
    movement_type = Column(String(30), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)

    # ── Relación polimórfica con tickets (solo si es un movimiento de ticket) ─
    source_app = Column(String(30), nullable=True)       # 'helpdesk' | 'maint'
    source_ticket_id = Column(Integer, nullable=True)    # ID en la tabla del app

    performed_by_id = Column(
        BigInteger, ForeignKey("core_users.id"), nullable=False
    )
    performed_at = Column(DateTime, nullable=False, server_default=func.now())
    notes = Column(Text, nullable=True)

    product = relationship("WarehouseProduct", back_populates="movements")
    entry = relationship("WarehouseStockEntry", back_populates="movements")
    performed_by = relationship("User", foreign_keys=[performed_by_id])

    __table_args__ = (
        Index("ix_warehouse_movements_product_at", "product_id", "performed_at"),
        Index("ix_warehouse_movements_source", "source_app", "source_ticket_id"),
        Index("ix_warehouse_movements_type_at", "movement_type", "performed_at"),
    )

    def __repr__(self) -> str:
        return f"<WarehouseMovement {self.id}: {self.movement_type} qty={self.quantity}>"
