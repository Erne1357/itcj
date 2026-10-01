"""Modelos de la app Sgc (Calidad) — tablas con prefijo ``sgc_``.

22 tablas (14 de entidad mutable + 5 de catálogo/singleton + 3 de asociación).
Todas las clases llevan el prefijo ``Sgc`` a propósito: dos de los nombres
"naturales" del dominio (``Area``, ``Document``) ya existen como clases
mapeadas sobre el mismo ``Base`` compartido (``helpdesk.models.area.Area`` y
``titulatec.models.document.Document`` — este último referenciado por un
``relationship("Document", ...)`` de **string sin calificar** en
``titulatec/models/process.py``). Reusar esos nombres aquí habría vuelto
ambiguo cualquier lookup por string de "Document" en el registro compartido
de SQLAlchemy (``configure_mappers()`` habría reventado con
``InvalidRequestError: Multiple classes found for path "Document"...``),
rompiendo TitulaTec. El prefijo ``Sgc`` en las 22 evita el problema de raíz
y es consistente en todo el paquete.

Gotcha del legacy a NO repetir: su ``models/__init__.py`` no exportaba
``IndicatorYear``/``Indicator``/``IndicatorTracking``, que solo se registraban
en el metadata por efecto colateral de importar el módulo. Aquí las 22 se
re-exportan explícitamente.
"""
from .structure import SgcArea, SgcProcess, sgc_user_areas
from .indicators import SgcIndicatorYear, SgcIndicator, SgcIndicatorTracking
from .mail_config import SgcMailConfig
from .documents import (
    SgcDocumentCategory,
    SgcDocumentClassification,
    SgcApprovalFlow,
    SgcApprovalFlowStep,
    sgc_flow_step_assignees,
    SgcDocument,
    SgcDocumentAcknowledgement,
    SgcDocumentVisibility,
)
from .incidents import SgcIncidentCategory, SgcIncident, SgcIncidentFile
from .programs import SgcProgramCategory, SgcProgramEvent, SgcProgramEventFile
from .tasks import (
    SgcTask, sgc_task_assignees, SgcTaskComment,
    SgcTaskCommentFile, SgcTaskApproval,
)

__all__ = [
    # Estructura
    "SgcArea",
    "sgc_user_areas",
    "SgcProcess",
    # Indicadores
    "SgcIndicatorYear",
    "SgcIndicator",
    "SgcIndicatorTracking",
    # Correo
    "SgcMailConfig",
    # Documentos y flujos
    "SgcDocumentCategory",
    "SgcDocumentClassification",
    "SgcApprovalFlow",
    "SgcApprovalFlowStep",
    "sgc_flow_step_assignees",
    "SgcDocument",
    "SgcDocumentAcknowledgement",
    "SgcDocumentVisibility",
    # Incidencias
    "SgcIncidentCategory",
    "SgcIncident",
    "SgcIncidentFile",
    # Programa (calendario)
    "SgcProgramCategory",
    "SgcProgramEvent",
    "SgcProgramEventFile",
    # Tareas
    "SgcTask",
    "sgc_task_assignees",
    "SgcTaskComment",
    "SgcTaskCommentFile",
    "SgcTaskApproval",
]
