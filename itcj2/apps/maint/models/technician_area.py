from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintTechnicianArea(Base):
    """
    Áreas de especialidad de cada técnico.
    Informativo — NO restringe qué tickets puede recibir el técnico.
    Permite al dispatcher saber quién tiene experiencia en qué.

    Valores de area_code:
        TRANSPORT | ELECTRICAL | CARPENTRY | AC | GARDENING | GENERAL | PAINTING
    """
    __tablename__ = 'maint_technician_areas'

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    area_code = Column(String(50), nullable=False)
    is_primary = Column(Boolean, nullable=False, server_default=text("FALSE"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # Relaciones
    user = relationship('User', foreign_keys=[user_id])
    updated_by = relationship('User', foreign_keys=[updated_by_id])

    __table_args__ = (
        Index('ix_maint_tech_area_user_code', 'user_id', 'area_code', unique=True),
        Index('ix_maint_tech_area_user', 'user_id'),
        Index('ix_maint_tech_area_code', 'area_code'),
    )
