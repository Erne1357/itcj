"""Bandeja de salida de correos del proceso de titulacion al egresado.

Motor D4 del spec `2026-09-28-titulatec-correos-notificaciones-design.md`
(enfoque A, "bandeja en BD"): cada evento que debe avisar por correo
(dictamen de documentos, avance/rechazo de fase, resultado de GTV, cita de
cotejo, recordatorios...) inserta una fila aqui EN LA MISMA transaccion que
lo origina -- el `enqueue` del servicio de encolado (tarea aparte) no hace
commit ni flush obligatorio, asi que si esa transaccion revierte la fila
nunca existio (Global Constraints, punto de revision #4). La tarea
periodica `titulatec.email_dispatch` (cada 5 minutos, `FOR UPDATE SKIP
LOCKED`) es la unica que envia y la unica que muta `status` fuera de la
insercion inicial.

`dedupe_key` (nullable, UNIQUE): solo los cuatro recordatorios
(`appt_reminder`, `docs_reminder`, `survey_reminder`, `library_reminder`)
la usan, con una llave estable por candidato (`{kind}:{id}` o
`{kind}:{pid}:{ancla}:{n}`).
El barrido inserta con `ON CONFLICT (dedupe_key) DO NOTHING`: correr la
tarea diaria dos veces no duplica filas. El resto de los `kind` la dejan
NULL -- Postgres permite multiples NULL bajo un UNIQUE normal, asi que
muchas filas sin recordatorio conviven sin chocar entre si.

`group_key` (nullable, SIN unicidad): agrupa filas que deben salir juntas
en un solo correo (D7) -- `docs:{process_id}` para el dictamen de
documentos de la fase 1 (incluye el `phase_approved` de esa fase),
`cita:{process_id}` para los cambios de cita (agendar/mover/cancelar). El
despachador las junta cuando la fila mas nueva del grupo lleva
`TITULATEC_EMAIL_DIGEST_MINUTES` sin movimiento y arma UN correo con el
estado VIGENTE al momento de enviar, no con el historial de cada fila.

`payload` guarda solo los hechos del evento ya congelados para el render
(nombres, motivos, fechas en ISO) -- **nunca** NIP, token, liga de
activacion ni contrasena (regla del plan; el correo del NIP jamas pasa por
esta tabla, D3).

CORREOS DE INSCRIPCION SIN SECRETO (spec 2026-10-05-titulatec-rendimiento-
design.md §3.7, decision P-D1; migracion `tt20261005d`). Cuatro de los
correos de `TitulaTecEmailHelper` -los que no llevan liga ni NIP- tambien
pasan por aqui (`ENROLLMENT_KINDS`): el aviso con folio al abrir la liga, el
rechazo de la solicitud, «ya tienes un proceso» y la revocacion. Una fila
cuelga del egresado (`user_id`, con o sin `process_id`) O de la solicitud
(`enrollment_request_id`): el rechazo de una solicitud se encola contra la
solicitud, que puede no tener usuario, asi que `user_id` es NULL-able. La
regla «toda fila lleva alumno o solicitud» es de la APLICACION, no un CHECK
de la BD: la valida `StudentMail.enqueue` antes de tocar la sesion y, como
red para cualquier otro escritor, el `before_insert` de abajo. Los correos
con liga o NIP (aprobar, reenviar la liga, dar acceso, reasignar NIP,
reenviar el aviso de acceso) NO pasan por esta tabla.

Escrita a mano junto con la migracion `tt20260928a` (misma tarea): los 5
nombres de indice/constraint de abajo estan declarados aqui Y en el
`op.create_table`/`op.create_index` de la migracion porque el CI arma el
esquema con `create_all` (sin Alembic) y dev/prod lo arman con Alembic --
si divergen, una base ve un indice que la otra no tiene. Lo mismo con
`enrollment_request_id` (`tt20261005d`): la FK sin nombre aqui toma el que
Postgres le da (`titulatec_email_outbox_enrollment_request_id_fkey`), que es
el que la migracion le pone a mano, y el indice de `index=True` se llama
`ix_titulatec_email_outbox_enrollment_request_id` en las dos.
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String,
    UniqueConstraint, event,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Dominio de `status` (spec C1/C3.7). Nace en 'pending'. 'sent' = entregado
# (subject/sent_to/sent_at quedan escritos). 'failed' = agoto
# TITULATEC_EMAIL_MAX_ATTEMPTS (last_error queda con el motivo legible).
# 'no_recipient' = D2: sin correo personal ni el de respaldo de la
# EnrollmentRequest -- nunca se manda al institucional. 'obsolete' = la
# re-validacion al enviar (D8) vio que ya no aplica, el proceso se revoco
# (C3.3) o el grupo de cita quedo en neto cero (D7: agendar+cancelar dentro
# de la espera).
OUTBOX_STATUSES = ("pending", "sent", "failed", "no_recipient", "obsolete")

# Catalogo cerrado de correos (spec §5), 17 kinds. `phase_approved` cubre
# DOS filas del catalogo (fase `initial_docs`, agrupada con `docs_review`;
# y el resto de las fases, individual) -- lo que cambia entre ambas es
# `group_key`, no el `kind`. Los 4 ultimos son del no adeudo de biblioteca
# (spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.11): pasa a Caja
# (o se corrige el monto), quedo liberado, se revirtio y el recordatorio del
# pago pendiente; todos individuales. Los 2 ultimos, «Con observaciones» de
# Biblioteca (spec 2026-10-05-titulatec-biblioteca-observaciones-design.md
# §3.3): observar (con el motivo) y rehabilitar; tambien individuales. Los 4
# del final son los correos de INSCRIPCION sin secreto (`ENROLLMENT_KINDS`,
# abajo; spec 2026-10-05-titulatec-rendimiento-design.md §3.7): individuales,
# sin `group_key`. Sin CHECK en la BD: crecer el catalogo no lleva migracion
# (lo fija `test_email_outbox_model.py`).
OUTBOX_KINDS = (
    "docs_review",
    "phase_approved",
    "phase_rejected",
    "survey_approved",
    "survey_rejected",
    "survey_revoked",
    "appt_changed",
    "appt_reminder",
    "appt_no_show",
    "docs_reminder",
    "survey_reminder",
    "library_ready",
    "library_cleared",
    "library_reverted",
    "library_reminder",
    "library_observed",
    "library_reenabled",
    "enrollment_verified",
    "enrollment_rejected",
    "already_enrolled",
    "process_cancelled",
)

# Correos de la INSCRIPCION que pasan por la bandeja (P-D1): el aviso con folio
# al abrir la liga (`EnrollmentRequestService.verify`), el rechazo
# (`.reject`), «ya tienes un proceso» (`.create`, rama del proceso vivo) y la
# revocacion (`ProcessService.cancel`). Mismas plantillas y destinatarios que
# su `TitulaTecEmailHelper.send_*`; el despachador los manda por su propio
# camino (`MailDispatcher._unidad_inscripcion`), no por el del proceso.
ENROLLMENT_KINDS = ("enrollment_verified", "enrollment_rejected", "already_enrolled",
                    "process_cancelled")

# Mensaje de la regla «alumno o solicitud» (lo que levanta el `before_insert`).
_SIN_ANCLA = ("Toda fila del outbox lleva alumno o solicitud "
              "(user_id o enrollment_request_id).")


class EmailOutbox(Base):
    __tablename__ = "titulatec_email_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_titulatec_email_outbox_dedupe_key"),
        # Llave del despachador (spec C3.1): filas `pending` con
        # `not_before <= ahora`, en lote.
        Index("ix_titulatec_email_outbox_status_not_before", "status", "not_before"),
    )

    id = Column(Integer, primary_key=True)

    kind = Column(String(40), nullable=False)                       # dominio: OUTBOX_KINDS (arriba)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                        nullable=True, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"),
                     nullable=True, index=True)                     # el egresado; NULL = fila de solicitud
    # La solicitud de inscripcion del correo (solo `ENROLLMENT_KINDS`). BigInteger
    # como `titulatec_enrollment_requests.id`. Ver la regla «alumno o solicitud».
    enrollment_request_id = Column(BigInteger,
                                   ForeignKey("titulatec_enrollment_requests.id"),
                                   nullable=True, index=True)
    group_key = Column(String(80), nullable=True, index=True)       # 'docs:{pid}' | 'cita:{pid}'
    dedupe_key = Column(String(160), nullable=True)                 # ver UniqueConstraint arriba

    payload = Column(JSON, nullable=False)                          # hechos del evento; nunca credenciales

    status = Column(String(20), nullable=False,
                    server_default=text("'pending'"))                # dominio: OUTBOX_STATUSES (arriba)
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    not_before = Column(DateTime, nullable=False, server_default=text("NOW()"))

    subject = Column(String(200), nullable=True)                    # se llena al enviar (bitacora)
    sent_to = Column(String(150), nullable=True)                    # a donde salio (bitacora)
    last_error = Column(String(255), nullable=True)                 # motivo legible del ultimo fallo

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    sent_at = Column(DateTime, nullable=True)

    process = relationship("TitulationProcess", foreign_keys=[process_id])

    def __repr__(self) -> str:
        return (f"<EmailOutbox {self.kind} u{self.user_id} "
                f"r{self.enrollment_request_id} {self.status}>")


@event.listens_for(EmailOutbox, "before_insert")
@event.listens_for(EmailOutbox, "before_update")
def _alumno_o_solicitud(_mapper, _connection, target) -> None:
    """La regla de la aplicacion (spec §3.7): ninguna fila sin `user_id` ni
    `enrollment_request_id`. `StudentMail.enqueue` ya la valida antes de tocar
    la sesion (asi nunca truena en el commit del llamador); esto es la red para
    cualquier otro escritor ORM."""
    if target.user_id is None and target.enrollment_request_id is None:
        raise ValueError(_SIN_ANCLA)
