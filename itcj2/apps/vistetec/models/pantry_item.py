from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class PantryItem(Base):
    """Tipos de artículos de despensa que se reciben."""
    __tablename__ = 'vistetec_pantry_items'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=True)  # enlatados, granos, higiene, mascotas
    unit = Column(String(20), nullable=True)       # pieza, kg, litro

    current_stock = Column(Integer, nullable=False, server_default=text("0"))

    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    donations = relationship('VTDonation', back_populates='pantry_item', lazy='dynamic')
    campaigns = relationship('PantryCampaign', back_populates='requested_item', lazy='dynamic')

    def __repr__(self):
        return f'<PantryItem {self.name} ({self.current_stock} {self.unit or "pzas"})>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'unit': self.unit,
            'current_stock': self.current_stock,
            'is_active': self.is_active,
        }
