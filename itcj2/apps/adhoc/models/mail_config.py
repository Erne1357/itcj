"""
Configuración global de correo de Calidad.

Singleton: la única fila (`id=1`) se siembra en
`database/DML/adhoc/init/05_seed_catalogs.sql`. **Prohibido crearla desde un
GET** — el legacy hacía `add()+commit()` dentro de `GET /api/mail/config`.
Se eliminan `sender_name`/`sender_email` (columnas muertas: el remitente sale
del buzón Graph conectado, no de config almacenada).
"""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class AdhocMailConfig(Base):
    __tablename__ = "adhoc_mail_config"

    id = Column(Integer, primary_key=True)
    is_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_adhoc_mail_config_singleton"),
    )

    def __repr__(self) -> str:
        return f"<AdhocMailConfig enabled={self.is_enabled}>"
