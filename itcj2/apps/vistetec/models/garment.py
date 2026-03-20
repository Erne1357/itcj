from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class Garment(Base):
    """Prenda de vestir registrada en VisteTec."""
    __tablename__ = 'vistetec_garments'

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(Text)
    category = Column(String(50), nullable=False, index=True)
    gender = Column(String(20))

    size = Column(String(20))
    brand = Column(String(50))
    color = Column(String(30))
    material = Column(String(50))
    condition = Column(String(20), nullable=False)

    status = Column(String(20), nullable=False, server_default=text("'available'"), index=True)
    # available, reserved, delivered, withdrawn

    image_path = Column(String(255))

    # Trazabilidad
    donated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    received_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    registered_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    delivered_to_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    delivered_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"), onupdate=func.now())

    # Relaciones
    donated_by = relationship('User', foreign_keys=[donated_by_id], lazy='joined')
    received_by = relationship('User', foreign_keys=[received_by_id], lazy='joined')
    registered_by = relationship('User', foreign_keys=[registered_by_id], lazy='joined')
    delivered_to = relationship('User', foreign_keys=[delivered_to_id], lazy='joined')
    delivered_by = relationship('User', foreign_keys=[delivered_by_id], lazy='joined')

    appointments = relationship('VTAppointment', back_populates='garment', lazy='dynamic')
    donation = relationship('VTDonation', back_populates='garment', uselist=False, lazy='joined')

    __table_args__ = (
        Index('ix_vistetec_garment_status_category', 'status', 'category'),
        Index('ix_vistetec_garment_gender_size', 'gender', 'size'),
    )

    def __repr__(self):
        return f'<Garment {self.code} - {self.name}>'

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'gender': self.gender,
            'size': self.size,
            'brand': self.brand,
            'color': self.color,
            'material': self.material,
            'condition': self.condition,
            'status': self.status,
            'image_path': self.image_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_relations:
            data['donated_by'] = self.donated_by.to_dict() if self.donated_by else None
            data['received_by'] = self.received_by.to_dict() if self.received_by else None
            data['registered_by'] = self.registered_by.to_dict() if self.registered_by else None
            data['delivered_to'] = self.delivered_to.to_dict() if self.delivered_to else None
            data['delivered_by'] = self.delivered_by.to_dict() if self.delivered_by else None
        return data
