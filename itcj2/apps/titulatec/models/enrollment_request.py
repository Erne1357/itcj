"""Solicitud de auto-inscripcion a una convocatoria (convocatoria abierta).

Estados (2026-09-15: toda solicitud pasa por la bandeja de Servicios Escolares
y el acceso llega solo por correo; el flujo completo esta en
`services/enrollment_request_service.py` y `docs/flows/xcut_public_enrollment.md`):

  pending_review --aprobar, SIN cuenta en core_users--> converted  (usuario + NIP por correo)
  pending_review --aprobar, CON cuenta--------------> approved   (liga de activacion por correo)
  approved --abrir la liga--------------------------> converted
  approved --la liga falla una revalidacion---------> pending_review (review_note = motivo)
  pending_review | approved | legado --rechazar-----> rejected

  `unverified` y `verified` son LEGADO del flujo con liga previa: ya no se
  escriben, pero sus filas se pueden aprobar o rechazar. Por eso el
  `server_default` sigue en 'unverified'; `create()` escribe 'pending_review'.

`kind` (known|unknown) se guarda al crear SOLO para mostrar: "tiene cuenta?" se
decide contra `core_users` al aprobar.

`verify_token_hash` es la liga de ACTIVACION de una cuenta que ya existe: la
emite la bandeja al aprobar (y la rota al reenviar) y viaja al correo personal
del formulario (`contact_email`). Fuera del legado solo hay hash mientras la
solicitud esta `approved` o ya `converted` (la liga convertida sigue resolviendo
para que el prefetch de un escaner de correo no la gaste). Se guarda HASHEADA
(sha256) y se compara con `hmac.compare_digest` (E7): un token en claro en BD es
una credencial en claro.

`contact_token_hash`/`contact_expires_at` son LEGADO SIN USO: la liga de
contacto dejo de emitirse y el 2026-09-15 se retiro tambien su canje
(`confirm_contact`, `GET /titulatec/inscripcion/correo` y su plantilla). Ningun
codigo las lee ni las escribe; se quedan en la BD para no migrar dos columnas
que siempre valen NULL en las filas nuevas.
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

    # LEGADO SIN USO desde 2026-09-15 (ver el docstring del modulo): nada las lee
    # ni las escribe. Quitarlas exige una migracion que hoy no aporta nada.
    contact_token_hash = Column(String(64), nullable=True, index=True)
    contact_expires_at = Column(DateTime, nullable=True)

    reviewed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(Text, nullable=True)
    # Sellada por `EnrollmentRequestService.reject()` en un commit PROPIO,
    # SOLO si `send_enrollment_rejected` devolvio True (mismo patron que
    # `verify_sent_at`/`_mail_activation`). NULL en una fila `rejected` es lo
    # que la bandeja pinta como "correo no enviado" (migracion `tt20260917a`).
    rejection_sent_at = Column(DateTime, nullable=True)
    converted_process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                                  nullable=True)
    created_ip_hash = Column(String(64), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return (f"<EnrollmentRequest {self.control_number} "
                f"c{self.cohort_id} {self.status}>")
