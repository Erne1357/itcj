"""Cita de cotejo de documentos (fase 2, Servicios Escolares)."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ReviewAppointment(Base):
    """Una cita de cotejo. Un proceso tiene como mucho una.

    Sobre `window_id`
    -----------------
    Es la ventana (y por tanto el encargado, el día y la rejilla de franjas) en
    la que cae la cita. Nullable solo por las citas heredadas de antes de que
    existieran las ventanas: la migración intenta casarlas por horario, y lo que
    no case se muestra en una banda «Otras citas de este día» en vez de
    esconderse. ``ON DELETE RESTRICT``: un espacio con citas no se borra, se
    pone en pausa.

    Sobre `change_request`
    ---------------------
    Antes la solicitud de cambio del alumno vivía en un prefijo mágico dentro de
    `note` (``"[CAMBIO] "``), y tanto `create` como `reschedule` hacían
    ``appt.note = note`` y **la pisaban**: la petición del alumno se perdía justo
    al reagendarlo. Además una nota operativa que empezara con ese prefijo se
    leía como solicitud del alumno. Ahora es columna propia y nadie más la toca.
    """
    __tablename__ = "titulatec_review_appointments"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    window_id = Column(
        Integer, ForeignKey("titulatec_review_windows.id", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    scheduled_at = Column(DateTime, nullable=False)
    location = Column(String(120), nullable=True)                   # 'Edificio A · Servicios Escolares'
    # scheduled|confirmed|in_progress|attended|no_show
    # La matriz de transiciones vive en AppointmentService._TRANSICIONES y se
    # valida ANTES de escribir: `no_show -> attended` era alcanzable.
    status = Column(String(20), nullable=False, server_default=text("'scheduled'"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    # Solicitud de cambio del alumno (columna propia, ver docstring).
    change_request = Column(Text, nullable=True)
    change_requested_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="review_appointments")
    window = relationship("ReviewWindow", back_populates="appointments")

    def __repr__(self) -> str:
        return f"<ReviewAppointment p{self.process_id} {self.status}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "window_id": self.window_id,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "location": self.location,
            "status": self.status,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "note": self.note,
            "change_request": self.change_request,
            "change_requested_at": (self.change_requested_at.isoformat()
                                    if self.change_requested_at else None),
        }
