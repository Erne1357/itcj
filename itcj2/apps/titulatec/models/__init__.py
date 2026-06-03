"""Modelos de TitulaTec.

Convención del proyecto: las CLASES van en inglés y SIN sufijo de app;
solo el ``__tablename__`` lleva el prefijo ``titulatec_``.
"""
from itcj2.apps.titulatec.models.modality import Modality
from itcj2.apps.titulatec.models.phase_definition import PhaseDefinition
from itcj2.apps.titulatec.models.document_type import DocumentType
from itcj2.apps.titulatec.models.cohort import Cohort
from itcj2.apps.titulatec.models.process import TitulationProcess
from itcj2.apps.titulatec.models.process_phase import ProcessPhase
from itcj2.apps.titulatec.models.document import Document
from itcj2.apps.titulatec.models.format_b import FormatB
from itcj2.apps.titulatec.models.synodal_assignment import SynodalAssignment
from itcj2.apps.titulatec.models.chat import ProcessChat, ChatMessage
from itcj2.apps.titulatec.models.review_appointment import ReviewAppointment
from itcj2.apps.titulatec.models.ceremony import Ceremony, CeremonyProcess
from itcj2.apps.titulatec.models.process_event import ProcessEvent

__all__ = [
    "Modality",
    "PhaseDefinition",
    "DocumentType",
    "Cohort",
    "TitulationProcess",
    "ProcessPhase",
    "Document",
    "FormatB",
    "SynodalAssignment",
    "ProcessChat",
    "ChatMessage",
    "ReviewAppointment",
    "Ceremony",
    "CeremonyProcess",
    "ProcessEvent",
]
