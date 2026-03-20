from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Category(Base):
    """
    Categorías para clasificar tickets (dinámicas, configurables por admin)
    Ejemplos:
    - Desarrollo: SII, SIILE, SIISAE, Moodle, Correo, AgendaTec, Tickets
    - Soporte: Hardware, Cableado, Proyectores, Impresoras, Red
    """
    __tablename__ = 'helpdesk_category'

    id = Column(Integer, primary_key=True)

    # Clasificación
    area = Column(String(20), nullable=False)  # 'DESARROLLO' | 'SOPORTE'
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Campos personalizados
    field_template = Column(JSON, nullable=True)

    # Estado y orden
    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    # Relaciones
    tickets = relationship('Ticket', back_populates='category', lazy='dynamic')

    # Índices
    __table_args__ = (
        Index('ix_helpdesk_category_area_active', 'area', 'is_active'),
    )

    def __repr__(self):
        return f'<Category {self.area}:{self.name}>'

    def to_dict(self, include_field_template=False):
        data = {
            'id': self.id,
            'area': self.area,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'display_order': self.display_order,
        }
        if include_field_template:
            data['field_template'] = self.field_template
        return data
