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
# `synodal_voted` NO está y no entrará: el voto de la fase 5 se escribe como
# `review_vote_cast` (uno por voto y versión, `ReviewService.vote`).
EVENT_TYPES = frozenset({
    # Proceso
    "process_created",
    "process_completed",
    "process_paused",              # `CohortService.set_window`, al cerrar la convocatoria
    "process_resumed",             # idem, al reabrirla
    "process_cancelled",           # `ProcessService.cancel`: SE revocó la inscripción
    "process_reactivated",         # `ProcessService.reactivate`: SE deshizo la revocación
    "enrollment_self_service",     # alta desde el formulario público
    "enrollment_access_reset",     # Centro de Cómputo reasignó el NIP (sin el NIP)
    # Documentos iniciales
    "document_uploaded",
    "document_approved",
    "document_rejected",
    "document_deleted",
    # La jefatura de SE pidió reemplazar uno en la cita de cotejo (spec
    # 2026-10-15-titulatec-reemplazo-cotejo-design.md §5):
    # `DocumentService.request_replacement`.
    "document_replacement_requested",
    # Fases
    "phase_approved",
    "phase_rejected",
    # Formato B (spec 2026-10-21 fase 3 §7/§8.5): cada envío (payload: ronda)
    # y la corrección del registro que hace Titulación (campos + motivo). Su
    # dictamen NO tiene evento propio: viaja en `phase_approved`/`_rejected`.
    "format_b_submitted",
    "format_b_registry_corrected",
    # Sinodales (spec 2026-10-21 fase 4 §10): el departamento académico registró
    # a los 4 (payload `{"synodals": [{"role", "user_id"}]}`: la posición va como
    # valor, porque la bitácora enmascara la llave «secretary»; el avance a la
    # fase 5 viaja en el `phase_approved` de siempre) o sustituyó a uno
    # (posición, saliente, entrante y motivo). Los escribe `SynodalService`.
    "synodals_assigned",
    "synodal_replaced",
    # Revisión de sinodales (spec 2026-10-22 fase 5 §11): el alumno subió una
    # versión del proyecto (payload `{"version"}`) o un sinodal votó la vigente
    # (`{"version", "role", "verdict"}`, la posición como VALOR). Los escribe
    # `ReviewService`; los mensajes del chat NO generan evento (viven en su
    # tabla) y la liberación es el `phase_approved` de siempre con payload.
    "review_version_uploaded",
    "review_vote_cast",
    # Anexo III (spec 2026-10-22 fase 6 §12): primera emision del folio
    # (`AnexoService.ensure_folio`, payload `{"folio", "semester"}`).
    "anexo_iii_issued",
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
    # Constancia previa de la encuesta (D9, spec 2026-10-01-titulatec-
    # biblioteca-caja-design.md §4.12): `SurveyReviewService.register_prior`.
    "survey_review_prior",
    # GTV entregó la constancia en papel de una previa importada (spec
    # 2026-10-05-titulatec-import-encuesta-xlsx-design.md D3):
    # `SurveyReviewService.mark_paper_delivered`.
    "survey_paper_delivered",
    # No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-
    # design.md §4.2/§4.12), «Con observaciones» (spec 2026-10-05) y la
    # observacion con adeudo (spec 2026-10-07 §2): los 11 que escribe
    # `LibraryClearanceService` (`LIBRARY_EVENT_TYPES`).
    "library_debt_registered",
    "library_no_charge",
    "library_amount_corrected",
    "library_payment_registered",
    "library_prior_registered",
    "library_payment_reverted",
    "library_clearance_reverted",
    "library_prior_undone",
    "library_observed",            # Biblioteca lo detuvo con un motivo (o lo actualizó)
    "library_reenabled",           # Biblioteca lo activó: vuelve a «Por revisar» (o a Caja, con adeudo)
    "library_cleared_after_observation",  # activó una con adeudo YA pagada: se libera (folio)
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
