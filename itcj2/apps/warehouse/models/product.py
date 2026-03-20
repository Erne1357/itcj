from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class WarehouseProduct(Base):
    """
    Producto del almacén global.

    El código (WAR-001) se genera en el service al crear.
    El total_stock y demás propiedades calculadas requieren que
    la relación stock_entries esté cargada (usar eager loading en el service).
    """

    __tablename__ = "warehouse_products"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    subcategory_id = Column(
        Integer, ForeignKey("warehouse_subcategories.id"), nullable=False
    )
    department_code = Column(String(50), nullable=False)
    unit_of_measure = Column(String(30), nullable=False)
    icon = Column(String(50), nullable=False, server_default=text("'bi-box'"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # ── Restock ──────────────────────────────────────────────────────────────
    restock_point_auto = Column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    restock_point_override = Column(Numeric(10, 2), nullable=True)
    restock_lead_time_days = Column(
        Integer, nullable=False, server_default=text("7")
    )
    last_restock_calc_at = Column(DateTime, nullable=True)
    restock_alert_sent_at = Column(DateTime, nullable=True)

    # ── Auditoría ─────────────────────────────────────────────────────────────
    created_by_id = Column(
        BigInteger, ForeignKey("core_users.id"), nullable=False
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())

    # ── Relaciones ────────────────────────────────────────────────────────────
    subcategory = relationship("WarehouseSubcategory", back_populates="products")
    created_by = relationship("User", foreign_keys=[created_by_id])
    stock_entries = relationship("WarehouseStockEntry", back_populates="product")
    movements = relationship("WarehouseMovement", back_populates="product")
    ticket_materials = relationship(
        "WarehouseTicketMaterial", back_populates="product"
    )

    __table_args__ = (
        Index(
            "ix_warehouse_products_subcategory_active", "subcategory_id", "is_active"
        ),
        Index("ix_warehouse_products_dept_active", "department_code", "is_active"),
        Index("ix_warehouse_products_code", "code"),
    )

    # ── Propiedades calculadas (requieren stock_entries cargado) ──────────────

    @property
    def restock_point(self) -> Decimal:
        if self.restock_point_override is not None:
            return self.restock_point_override
        return self.restock_point_auto

    @property
    def total_stock(self) -> Decimal:
        return sum(
            (e.quantity_remaining for e in self.stock_entries if e.is_available),
            Decimal("0"),
        )

    @property
    def is_below_restock(self) -> bool:
        return self.total_stock <= self.restock_point

    @property
    def total_stock_value(self) -> Decimal:
        return sum(
            (e.quantity_remaining * e.unit_cost for e in self.stock_entries if e.is_available),
            Decimal("0"),
        )

    def __repr__(self) -> str:
        return f"<WarehouseProduct {self.code}: {self.name}>"
