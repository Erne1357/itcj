"""Regla del motor de asignacion automatica de tickets.

Coincide por area + categoria (opcional) + prioridad (opcional); gana la mas
especifica. La terna unica (area, categoria, prioridad) se valida en el service
(un UNIQUE de Postgres no atrapa NULL).
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index,
    Integer, JSON, String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base

STRATEGIES = ("round_robin", "least_loaded")


class AssignmentRule(Base):
    __tablename__ = "helpdesk_assignment_rules"

    id = Column(Integer, primary_key=True)
    area = Column(String(30), nullable=False)
    category_id = Column(Integer, ForeignKey("helpdesk_category.id"), nullable=True)
    priority = Column(String(20), nullable=True)  # code de helpdesk_priority
    strategy = Column(String(20), nullable=False)
    technician_ids = Column(JSON, nullable=False)  # lista ordenada = orden de turnos
    last_assigned_user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    category = relationship("Category")

    __table_args__ = (
        CheckConstraint(
            "strategy IN ('round_robin','least_loaded')",
            name="ck_helpdesk_assignment_rules_strategy",
        ),
        Index("ix_helpdesk_assignment_rules_area_active", "area", "is_active"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "area": self.area,
            "category_id": self.category_id,
            "priority": self.priority,
            "strategy": self.strategy,
            "technician_ids": list(self.technician_ids or []),
            "last_assigned_user_id": self.last_assigned_user_id,
            "is_active": self.is_active,
            "created_by_id": self.created_by_id,
            "updated_by_id": self.updated_by_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
