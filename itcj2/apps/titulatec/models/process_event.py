"""Auditoría / timeline de eventos de un proceso."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Vocabulario CERRADO de `event_type` (2026-09-18). Antes vivía como un
# comentario a medias al lado de la columna («phase_approved|document_uploaded|
# synodal_voted|…»), que no obligaba a nada: los dos historiales de la app
# —`pages/student.py::_EVENT_LABELS` y `pages/admin.py::_EVENT_UI`— tenían
# huecos distintos y cada hueco se veía como el CÓDIGO CRUDO en pantalla, en
# inglés y con guiones bajos, delante del egresado.
#
# Esta lista es la fuente de verdad, y `test_event_labels.py` cruza los dos
# mapas contra ella. **Un `event_type` nuevo se agrega AQUÍ y en los dos
# mapas, o el test falla.** Ese es todo el punto: que el próximo no se entere
# el usuario por una captura de pantalla.
#
# `synodal_voted` NO está: la fase 4 tiene tablas y permisos pero ninguna ruta
# que escriba el evento (CLAUDE.md de la app, §10). Entra cuando se escriba.
EVENT_TYPES = frozenset({
    # Proceso
    "process_created",
    "process_completed",
    "process_paused",              # `CohortService.set_window`, al cerrar la convocatoria
    "process_resumed",             # idem, al reabrirla
    "enrollment_self_service",     # alta desde el formulario público
    "enrollment_access_reset",     # Centro de Cómputo reasignó el NIP (sin el NIP)
    # Documentos iniciales
    "document_uploaded",
    "document_approved",
    "document_rejected",
    "document_deleted",
    # Fases
    "phase_approved",
    "phase_rejected",
    # Requisitos de cotejo
    "requirement_fulfilled",
    "requirement_unfulfilled",
    # Cita de cotejo
    "appointment_scheduled",
    "appointment_confirmed",
    "appointment_rescheduled",
    "appointment_change_requested",
    "appointment_in_progress",
    "appointment_attended",
    "appointment_no_show",
    "appointment_undo_no_show",
    "appointment_cancelled",
    # Liberación de la encuesta de egresados (GTV)
    "survey_review_submitted",
    "survey_review_approved",
    "survey_review_rejected",
    "survey_review_revoked",
})


class ProcessEvent(Base):
    __tablename__ = "titulatec_process_events"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    actor_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    event_type = Column(String(40), nullable=False)                 # dominio: EVENT_TYPES (arriba)
    phase_number = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)

    process = relationship("TitulationProcess", back_populates="events")

    def __repr__(self) -> str:
        return f"<ProcessEvent p{self.process_id} {self.event_type}>"
