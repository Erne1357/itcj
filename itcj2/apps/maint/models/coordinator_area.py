"""
Modelo para el mapeo coordinador de área ↔ área de mantenimiento.

Solo los coordinadores de ÁREA necesitan filas aquí.
Los coordinadores GENERALES se identifican únicamente por su rol
(maint_general_coordinator) y NO requieren entradas en esta tabla.

area_code enlaza por código con maint_area (catálogo) sin FK rígida,
igual que maint_technician_areas.
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintCoordinatorArea(Base):
    """
    Mapeo de qué área(s) cubre cada coordinador de área.

    Valores esperados de area_code (catálogo maint_area):
        TRANSPORT | ELECTRICAL | CARPENTRY | AC | GARDENING | GENERAL | PAINTING
    """
    __tablename__ = 'maint_coordinator_areas'

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    area_code = Column(String(30), nullable=False)
    is_primary = Column(Boolean, nullable=False, server_default=text("FALSE"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # Relaciones — foreign_keys explícitos por ambigüedad (dos FKs a core_users)
    user = relationship('User', foreign_keys=[user_id])
    created_by = relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        UniqueConstraint('user_id', 'area_code', name='uq_maint_coordinator_areas_user_area'),
        Index('ix_maint_coordinator_areas_user_id', 'user_id'),
        Index('ix_maint_coordinator_areas_area_code', 'area_code'),
    )
