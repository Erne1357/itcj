"""DVR con credenciales cifradas (Fernet, `CAMERAS_SECRET_KEY`) y sus departamentos."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    SmallInteger, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class DvrDepartment(Base):
    __tablename__ = "cameras_dvr_departments"

    dvr_id = Column(Integer, ForeignKey("cameras_dvrs.id", ondelete="CASCADE"), primary_key=True)
    department_id = Column(Integer, ForeignKey("core_departments.id"), primary_key=True)

    __table_args__ = (
        Index("ix_cameras_dvr_departments_department_id", "department_id"),
    )


# Forma física de las cámaras instaladas: código -> etiqueta (única fuente).
CAMERA_TYPES = {"bala": "Bala", "ptz": "PTZ", "mixtas": "Bala y PTZ"}


class Dvr(Base):
    __tablename__ = "cameras_dvrs"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    location = Column(String(150))
    brand = Column(String(50))
    model = Column(String(80))
    channels = Column(SmallInteger)
    camera_type = Column(String(10))               # bala | ptz | mixtas (CAMERA_TYPES)
    cameras_bala = Column(Integer)
    cameras_ptz = Column(Integer)
    username = Column(String(50))                  # en claro: casi siempre `admin`
    password_cipher = Column(Text)                 # token Fernet, nunca en claro
    pattern_cipher = Column(Text)                  # token Fernet de la secuencia
    notes = Column(Text)                           # en claro: la UI advierte

    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        CheckConstraint("camera_type IN ('bala','ptz','mixtas')", name="ck_cameras_dvrs_camera_type"),
        CheckConstraint("cameras_bala BETWEEN 0 AND 128", name="ck_cameras_dvrs_cameras_bala"),
        CheckConstraint("cameras_ptz BETWEEN 0 AND 128", name="ck_cameras_dvrs_cameras_ptz"),
    )

    # Sin passive_deletes la sesión intentaría anular dvr_id; la BD ya cascadea.
    departments = relationship(
        "Department", secondary="cameras_dvr_departments", lazy="selectin",
        passive_deletes=True,
    )
