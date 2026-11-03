"""Foto de credencial: una por estudiante. El archivo vive fuera de static/."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from itcj2.models.base import Base


class CredentialPhoto(Base):
    __tablename__ = "credencial_photos"

    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True)
    # Aleatorio; es lo que viaja en el token, nunca el user_id.
    ref = Column(String(24), unique=True, nullable=False, index=True)
    file_name = Column(String(40), unique=True, nullable=False)  # {uuid4().hex}.jpg
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    def __repr__(self):
        return f"<CredentialPhoto user_id={self.user_id}>"
