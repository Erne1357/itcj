from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintCategory(Base):
    """
    Categorías de mantenimiento.

    Valores de code:
        TRANSPORT | GENERAL | ELECTRICAL | CARPENTRY | AC | GARDENING
    """
    __tablename__ = 'maint_categories'

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=False, server_default=text("'bi-tools'"))
    field_template = Column(JSON, nullable=True)   # Campos dinámicos por categoría
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))

    # Relaciones
    tickets = relationship('MaintTicket', back_populates='category')

    __table_args__ = (
        Index('ix_maint_categories_active_order', 'is_active', 'display_order'),
    )
