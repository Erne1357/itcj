from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class WarehouseSubcategory(Base):
    """Subcategoría dentro de una categoría del almacén."""

    __tablename__ = "warehouse_subcategories"

    id = Column(Integer, primary_key=True)
    category_id = Column(
        Integer, ForeignKey("warehouse_categories.id"), nullable=False
    )
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    category = relationship("WarehouseCategory", back_populates="subcategories")
    products = relationship("WarehouseProduct", back_populates="subcategory")

    __table_args__ = (
        UniqueConstraint(
            "category_id", "name", name="uq_warehouse_subcategories_cat_name"
        ),
        Index("ix_warehouse_subcategories_cat_active", "category_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<WarehouseSubcategory {self.id}: {self.name}>"
