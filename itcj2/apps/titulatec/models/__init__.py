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
from itcj2.apps.titulatec.models.cohort_review_day import CohortReviewDay  # noqa: F401
from itcj2.apps.titulatec.models.cotejo_requirement import CotejoRequirement  # noqa: F401
from itcj2.apps.titulatec.models.review_window import ReviewWindow  # noqa: F401
from itcj2.apps.titulatec.models.survey import (  # noqa: F401
    SurveyForm, SurveyResponse, SurveyAnswer, SurveyDraft,
)
from itcj2.apps.titulatec.models.requirement_fulfillment import (  # noqa: F401
    RequirementFulfillment,
)
from itcj2.apps.titulatec.models.enrollment_request import EnrollmentRequest  # noqa: F401
from itcj2.apps.titulatec.models.survey_review import SurveyReview  # noqa: F401
from itcj2.apps.titulatec.models.eligibility_check import EligibilityCheck  # noqa: F401
from itcj2.apps.titulatec.models.email_outbox import EmailOutbox  # noqa: F401
from itcj2.apps.titulatec.models.library_clearance import LibraryClearance  # noqa: F401
from itcj2.apps.titulatec.models.certificate import (  # noqa: F401
    Certificate, CertificateBatch, CertificateCounter,
)
from itcj2.apps.titulatec.models.prior_clearance import PriorClearance  # noqa: F401
from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog  # noqa: F401

# Alias de comodidad (spec: «AuditLog»). La clase real se llama distinto porque
# agendatec ya registra una `AuditLog` en el mismo `Base`. Fuera de `__all__`.
AuditLog = TitulatecAuditLog

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
    "CohortReviewDay",
    "CotejoRequirement",
    "ReviewWindow",
    "SurveyForm",
    "SurveyResponse",
    "SurveyAnswer",
    "SurveyDraft",
    "RequirementFulfillment",
    "EnrollmentRequest",
    "SurveyReview",
    "EligibilityCheck",
    "EmailOutbox",
    "LibraryClearance",
    "Certificate",
    "CertificateBatch",
    "CertificateCounter",
    "PriorClearance",
    "TitulatecAuditLog",
]

# Bitácora (spec 2026-10-07 §4.4): la escucha `after_flush` se instala AQUÍ, al
# final del paquete. Todo import de un modelo de TitulaTec (también el de un
# submódulo suelto) ejecuta antes este `__init__`, así que la escucha existe en
# HTTP, Celery, CLI y pruebas antes del primer flush que pueda tocar una tabla
# `titulatec_*`. `audit_listeners` no importa modelos al cargarse: sin ciclo.
from itcj2.apps.titulatec.services import audit_listeners as _audit_listeners  # noqa: E402

_audit_listeners.install()
