"""
Modelo para el catálogo de áreas de tickets (editable desde la UI).
Reemplaza los strings hardcoded 'DESARROLLO'/'SOPORTE' en ticket_service.py
y en las validaciones de categories.py.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Area(Base):
    """
    Catálogo de áreas de atención del helpdesk.
    Las áreas son fijas (DESARROLLO y SOPORTE); solo se permite editar
    su metadata (label, icon, color, description, display_order, is_active).
    """
    __tablename__ = 'helpdesk_area'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(30), nullable=False, unique=True, index=True)
    # Valores canónicos: DESARROLLO | SOPORTE
    label = Column(String(80), nullable=False)

    # --- Presentación ---
    icon = Column(String(60), nullable=True)    # ej: fa-laptop-code, fa-wrench
    color = Column(String(20), nullable=True)   # hex o nombre CSS, ej: #198754
    description = Column(Text, nullable=True)

    # --- Ordenamiento ---
    display_order = Column(Integer, default=0)

    # --- Auditoría ---
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    def __repr__(self):
        return f'<Area {self.code}: {self.label}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'icon': self.icon,
            'color': self.color,
            'description': self.description,
            'display_order': self.display_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
