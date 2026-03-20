from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class WarehouseStockEntry(Base):
    """
    Lote / entrada de stock — base del sistema FIFO.

    El FIFO se ordena por purchase_date ASC.
    """

    __tablename__ = "warehouse_stock_entries"

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer, ForeignKey("warehouse_products.id"), nullable=False
    )
    quantity_original = Column(Numeric(10, 2), nullable=False)
    quantity_remaining = Column(Numeric(10, 2), nullable=False)
    purchase_date = Column(Date, nullable=False)          # ← clave para FIFO
    purchase_folio = Column(String(100), nullable=False)
    unit_cost = Column(Numeric(10, 4), nullable=False)
    supplier = Column(String(200), nullable=True)
    registered_by_id = Column(
        BigInteger, ForeignKey("core_users.id"), nullable=False
    )
    registered_at = Column(DateTime, nullable=False, server_default=func.now())
    notes = Column(Text, nullable=True)
    is_exhausted = Column(Boolean, nullable=False, server_default=text("FALSE"))
    voided = Column(Boolean, nullable=False, server_default=text("FALSE"))
    voided_by_id = Column(
        BigInteger, ForeignKey("core_users.id"), nullable=True
    )
    voided_at = Column(DateTime, nullable=True)
    void_reason = Column(Text, nullable=True)

    product = relationship("WarehouseProduct", back_populates="stock_entries")
    registered_by = relationship("User", foreign_keys=[registered_by_id])
    voided_by = relationship("User", foreign_keys=[voided_by_id])
    movements = relationship("WarehouseMovement", back_populates="entry")

    __table_args__ = (
        Index(
            "ix_warehouse_stock_entries_product_date", "product_id", "purchase_date"
        ),
        Index(
            "ix_warehouse_stock_entries_product_status",
            "product_id", "is_exhausted", "voided",
        ),
    )

    @property
    def is_available(self) -> bool:
        return not self.is_exhausted and not self.voided

    @property
    def quantity_consumed(self) -> Decimal:
        return self.quantity_original - self.quantity_remaining

    def __repr__(self) -> str:
        return f"<WarehouseStockEntry {self.id}: product={self.product_id} remaining={self.quantity_remaining}>"
