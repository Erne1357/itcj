"""NIPs del SII precargados, cifrados, a la espera de la aprobación.

Spec 2026-10-13-titulatec-nip-precargado-design.md §4. Servicios Escolares
carga por lote el NIP que el SII ya tiene para cada egresado; la aprobación lo
usa para crear la cuenta sin consultar al SII en ese momento. El NIP vive
CIFRADO (Fernet, `TITULATEC_NIP_STASH_KEY`) y la fila se borra al usarse o al
cerrar la convocatoria: esta tabla nunca es un archivo de NIPs en claro.

Escrita a mano junto con la migración `tt20261013a`: PK/FK sin nombre explícito
(toman el de Postgres, igual en `create_all` y en Alembic), así que CI
(`create_all`) y dev/prod (Alembic) arman la misma tabla.
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import text

from itcj2.models.base import Base


class NipStash(Base):
    __tablename__ = "titulatec_nip_stash"

    # Número de control ya normalizado (`import_service.normalize_control`).
    control_number = Column(String(20), primary_key=True)
    # Token Fernet (ASCII url-safe). Nunca el NIP en claro.
    nip_cipher = Column(Text, nullable=False)
    loaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    loaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
