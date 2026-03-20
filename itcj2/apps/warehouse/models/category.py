from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class WarehouseCategory(Base):
    """Categoría de productos del almacén (ej: Cables, Herramientas)."""

    __tablename__ = "warehouse_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=False, server_default=text("'bi-box-seam'"))
    # NULL = categoría global visible para todos los admins
    department_code = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())

    subcategories = relationship(
        "WarehouseSubcategory",
        back_populates="category",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_warehouse_categories_dept_active", "department_code", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<WarehouseCategory {self.id}: {self.name}>"
