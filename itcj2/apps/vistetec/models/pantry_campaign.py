from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class PantryCampaign(Base):
    """Campañas de recolección de despensa."""
    __tablename__ = 'vistetec_pantry_campaigns'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    requested_item_id = Column(Integer, ForeignKey('vistetec_pantry_items.id'), nullable=True)
    goal_quantity = Column(Integer, nullable=True)
    collected_quantity = Column(Integer, nullable=False, server_default=text("0"))

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"), onupdate=func.now())

    # Relaciones
    requested_item = relationship('PantryItem', back_populates='campaigns', lazy='joined')

    def __repr__(self):
        return f'<PantryCampaign {self.name}>'

    @property
    def progress_percentage(self):
        if not self.goal_quantity or self.goal_quantity == 0:
            return 0
        return min(100, round((self.collected_quantity / self.goal_quantity) * 100))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'requested_item_id': self.requested_item_id,
            'requested_item': self.requested_item.to_dict() if self.requested_item else None,
            'goal_quantity': self.goal_quantity,
            'collected_quantity': self.collected_quantity,
            'progress_percentage': self.progress_percentage,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active,
        }
