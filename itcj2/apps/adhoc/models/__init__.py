"""Modelos de la app Adhoc (Calidad) — tablas con prefijo ``adhoc_``.

22 tablas (14 de entidad mutable + 5 de catálogo/singleton + 3 de asociación).
Todas las clases llevan el prefijo ``Adhoc`` a propósito: dos de los nombres
"naturales" del dominio (``Area``, ``Document``) ya existen como clases
mapeadas sobre el mismo ``Base`` compartido (``helpdesk.models.area.Area`` y
``titulatec.models.document.Document`` — este último referenciado por un
``relationship("Document", ...)`` de **string sin calificar** en
``titulatec/models/process.py``). Reusar esos nombres aquí habría vuelto
ambiguo cualquier lookup por string de "Document" en el registro compartido
de SQLAlchemy (``configure_mappers()`` habría reventado con
``InvalidRequestError: Multiple classes found for path "Document"...``),
rompiendo TitulaTec. El prefijo ``Adhoc`` en las 22 evita el problema de raíz
y es consistente en todo el paquete.

Gotcha del legacy a NO repetir: su ``models/__init__.py`` no exportaba
``IndicatorYear``/``Indicator``/``IndicatorTracking``, que solo se registraban
en el metadata por efecto colateral de importar el módulo. Aquí las 22 se
re-exportan explícitamente.
"""
from .structure import AdhocArea, AdhocProcess, adhoc_user_areas
from .indicators import AdhocIndicatorYear, AdhocIndicator, AdhocIndicatorTracking
from .mail_config import AdhocMailConfig
from .documents import (
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    adhoc_flow_step_assignees,
    AdhocDocument,
)
from .incidents import AdhocIncidentCategory, AdhocIncident
from .programs import AdhocProgramCategory, AdhocProgramEvent, AdhocProgramEventFile
from .tasks import AdhocTask, adhoc_task_assignees, AdhocTaskComment, AdhocTaskApproval

__all__ = [
    # Estructura
    "AdhocArea",
    "adhoc_user_areas",
    "AdhocProcess",
    # Indicadores
    "AdhocIndicatorYear",
    "AdhocIndicator",
    "AdhocIndicatorTracking",
    # Correo
    "AdhocMailConfig",
    # Documentos y flujos
    "AdhocDocumentCategory",
    "AdhocDocumentClassification",
    "AdhocApprovalFlow",
    "AdhocApprovalFlowStep",
    "adhoc_flow_step_assignees",
    "AdhocDocument",
    # Incidencias
    "AdhocIncidentCategory",
    "AdhocIncident",
    # Programa (calendario)
    "AdhocProgramCategory",
    "AdhocProgramEvent",
    "AdhocProgramEventFile",
    # Tareas
    "AdhocTask",
    "adhoc_task_assignees",
    "AdhocTaskComment",
    "AdhocTaskApproval",
]
