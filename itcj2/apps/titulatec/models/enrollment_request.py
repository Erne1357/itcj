"""Solicitud de auto-inscripcion a una convocatoria (convocatoria abierta).

Estados:
  conocido:     unverified -> verified -> converted
  desconocido:  unverified -> pending_review -> approved -> converted | rejected
  conocido cuyo correo institucional no responde tras 3 envios:
                unverified -> pending_review

Dos buzones, dos tokens, a proposito (D17):
  `verify_token_hash`  decide la INSCRIPCION. Para un alumno conocido viaja a su
                       correo institucional (`student_email(user)`), que es lo
                       unico que prueba que es el; para un desconocido, al
                       correo personal que escribio, que es el unico que hay.
  `contact_token_hash` confirma el correo PERSONAL. No bloquea nada; solo pone
                       `core_student_profile.contact_email_verified_at`.

Los tokens se guardan HASHEADOS (sha256) y se comparan con `hmac.compare_digest`
(E7): un token en claro en BD es una credencial en claro.
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Estados VIVOS: una solicitud en cualquiera de ellos ocupa el lugar del par
# (convocatoria, numero de control). `approved` entra el 2026-09-15: es la liga
# de activacion en camino, y otra solicitud viva del mismo control abriria una
# segunda liga (o un NIP) para la misma persona. `unverified` y `verified` son
# estados legado que ya no se escriben, pero siguen protegiendo filas viejas.
OPEN_STATUSES = ("unverified", "verified", "pending_review", "approved")
_OPEN_PREDICATE = "status IN (" + ",".join(f"'{s}'" for s in OPEN_STATUSES) + ")"


class EnrollmentRequest(Base):
    __tablename__ = "titulatec_enrollment_requests"
    # Un UniqueConstraint normal no sirve: impediria reintentar despues de un
    # rechazo. El indice PARCIAL deja fuera 'rejected' y 'converted' y solo
    # prohibe duplicados VIVOS. Se declara aqui ademas de en la migracion
    # (`tt20260915a`) porque el `create_all` del CI no pasa por Alembic; los dos
    # predicados los amarra `test_el_modelo_y_la_migracion_declaran_el_mismo_predicado`.
    __table_args__ = (
        Index("uq_titulatec_enrollment_req_open", "cohort_id", "control_number",
              unique=True,
              postgresql_where=text(_OPEN_PREDICATE)),
    )

    id = Column(BigInteger, primary_key=True)
    cohort_id = Column(Integer, ForeignKey("titulatec_cohorts.id"),
                       nullable=False, index=True)
    control_number = Column(String(20), nullable=False, index=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    middle_name = Column(String(80), nullable=True)
    program_id = Column(Integer, ForeignKey("core_programs.id"), nullable=True)
    program_text = Column(String(160), nullable=True)
    phone = Column(String(20), nullable=False)
    contact_email = Column(String(150), nullable=False)
    has_efirma = Column(Boolean, nullable=False)
    kind = Column(String(10), nullable=False)                  # known|unknown
    status = Column(String(20), nullable=False,
                    server_default=text("'unverified'"))

    verify_token_hash = Column(String(64), nullable=True, index=True)
    verify_expires_at = Column(DateTime, nullable=True)
    verify_sent_at = Column(DateTime, nullable=True)
    verify_send_count = Column(Integer, nullable=False, server_default=text("0"))
    verify_sent_to = Column(String(150), nullable=True)        # a que buzon se mando
    verified_at = Column(DateTime, nullable=True)

    contact_token_hash = Column(String(64), nullable=True, index=True)
    contact_expires_at = Column(DateTime, nullable=True)

    reviewed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(Text, nullable=True)
    converted_process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                                  nullable=True)
    created_ip_hash = Column(String(64), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return (f"<EnrollmentRequest {self.control_number} "
                f"c{self.cohort_id} {self.status}>")
