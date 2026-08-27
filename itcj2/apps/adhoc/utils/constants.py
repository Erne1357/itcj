"""Vocabularios cerrados de la app Adhoc (Calidad / SGC ISO 9001).

**Fuente única de verdad.** Cada tupla de este módulo replica, literal y en el
mismo orden, un ``CheckConstraint`` ya aplicado en la base de datos. Verificado
contra ``pg_constraint`` el 2026-08-25 (migración ``23004eb05186``)::

    SELECT conname || ' :: ' || pg_get_constraintdef(oid)
      FROM pg_constraint
     WHERE conrelid::regclass::text LIKE 'adhoc%' AND contype = 'c';

Regla de uso (plan §2.8): **todo campo con ``CheckConstraint`` se declara en
Pydantic como el ``Literal`` de este módulo, nunca como ``str``**. Los defaults
``*_DEFAULT`` son los mismos que el ``server_default`` de la columna, y existen
aquí porque un ``None`` entrante (radio sin marcar, ``<select>`` en el
placeholder) tiene que resolverse al default *antes* de tocar el ORM.

Ojo con los acentos y el género: ``'En Revisión'``, ``'Completada'`` (tarea),
``'Completado'`` (evento de programa), ``'No Iniciada'`` (incidencia),
``'Rechazada'`` (tarea) vs ``'Rechazado'`` (documento). El legacy los mezclaba
—escribía ``'Completado'`` también en incidencias, valor que su propia UI no
reconocía— y por eso ahora son constantes con nombre en vez de literales
sueltos repartidos por los services.
"""
from typing import Final, Literal

__all__ = [
    # Documentos
    "DocumentStatus", "DOCUMENT_STATUSES", "DOCUMENT_STATUS_DEFAULT",
    "DOCUMENT_STATUS_DRAFT", "DOCUMENT_STATUS_IN_REVIEW",
    "DOCUMENT_STATUS_APPROVED", "DOCUMENT_STATUS_REJECTED",
    "DOCUMENT_STATUS_OBSOLETE",
    "DOCUMENT_STATUSES_STARTABLE", "DOCUMENT_STATUSES_VIA_PATCH",
    # Incidencias
    "IncidentStatus", "INCIDENT_STATUSES", "INCIDENT_STATUS_DEFAULT",
    "INCIDENT_STATUS_NOT_STARTED", "INCIDENT_STATUS_STARTED", "INCIDENT_STATUS_CLOSED",
    # Eventos de programa
    "ProgramEventStatus", "PROGRAM_EVENT_STATUSES", "PROGRAM_EVENT_STATUS_DEFAULT",
    "PROGRAM_EVENT_STATUS_PLANNED", "PROGRAM_EVENT_STATUS_IN_PROGRESS",
    "PROGRAM_EVENT_STATUS_COMPLETED",
    # Tareas
    "TaskStatus", "TASK_STATUSES", "TASK_STATUS_DEFAULT",
    "TASK_STATUS_PENDING", "TASK_STATUS_IN_PROGRESS", "TASK_STATUS_IN_REVIEW",
    "TASK_STATUS_WAITING", "TASK_STATUS_COMPLETED", "TASK_STATUS_REJECTED",
    "TASK_OPEN_STATUSES",
    # Prioridades
    "Priority", "PRIORITIES", "PRIORITY_DEFAULT",
    "PRIORITY_LOW", "PRIORITY_MEDIUM", "PRIORITY_HIGH", "PRIORITY_URGENT",
    # Indicadores
    "IndicatorFrequency", "INDICATOR_FREQUENCIES",
    "TrackingColor", "TRACKING_COLORS", "TRACKING_COLOR_DEFAULT",
    "TRACKING_COLOR_WHITE", "TRACKING_COLOR_RED",
    "TRACKING_COLOR_YELLOW", "TRACKING_COLOR_GREEN",
    "TRACKING_PERIODS_BY_FREQUENCY",
    # Workflow
    "ApprovalDecision", "APPROVAL_DECISIONS",
    "APPROVAL_DECISION_APPROVED", "APPROVAL_DECISION_REJECTED",
    "WorkflowAction", "WORKFLOW_ACTIONS",
    "WORKFLOW_ACTION_FINISH", "WORKFLOW_ACTION_REJECT", "WORKFLOW_ACTION_APPROVE",
    # Otros
    "TaskParentType", "TASK_PARENT_TYPES",
    "UploadKind", "UPLOAD_KINDS",
    "ReportType", "REPORT_TYPES",
    "APP_KEY", "APP_LABEL",
]

# --------------------------------------------------------------------------
# Identidad de la app
# --------------------------------------------------------------------------

APP_KEY: Final[str] = "adhoc"
APP_LABEL: Final[str] = "Calidad"


# --------------------------------------------------------------------------
# Documentos — ck_adhoc_documents_status
# --------------------------------------------------------------------------

DOCUMENT_STATUS_DRAFT: Final[str] = "Borrador"
DOCUMENT_STATUS_IN_REVIEW: Final[str] = "En Revisión"
DOCUMENT_STATUS_APPROVED: Final[str] = "Aprobado"
DOCUMENT_STATUS_REJECTED: Final[str] = "Rechazado"
#: Versión superada por otra más nueva de la misma cadena. Es un estado
#: TERMINAL: un documento obsoleto no vuelve a flujo (ver
#: ``DOCUMENT_STATUSES_STARTABLE``). Lo introdujo la migración del SGC legacy,
#: donde ``dap_approval_status = 2`` marca 59 de 206 documentos como superados.
DOCUMENT_STATUS_OBSOLETE: Final[str] = "Obsoleto"

DocumentStatus = Literal["Borrador", "En Revisión", "Aprobado", "Rechazado", "Obsoleto"]
DOCUMENT_STATUSES: Final[tuple[str, ...]] = (
    "Borrador", "En Revisión", "Aprobado", "Rechazado", "Obsoleto",
)
DOCUMENT_STATUS_DEFAULT: Final[str] = DOCUMENT_STATUS_DRAFT

#: Estados desde los que se puede arrancar un flujo de aprobación. Los demás
#: son producto del motor de flujo o terminales, y el PATCH genérico no debe
#: poder escribirlos (ver ``AdhocDocumentService.update``).
DOCUMENT_STATUSES_STARTABLE: Final[tuple[str, ...]] = (
    DOCUMENT_STATUS_DRAFT, DOCUMENT_STATUS_REJECTED,
)
#: Estados que el PATCH genérico SÍ puede escribir. 'En Revisión', 'Aprobado' y
#: 'Rechazado' los produce el motor de flujo: dejarlos aquí permitiría marcar
#: aprobado un documento cuyo flujo sigue en el primer paso, con
#: ``adhoc_task_approvals`` vacío y ``current_step_id`` colgando.
DOCUMENT_STATUSES_VIA_PATCH: Final[tuple[str, ...]] = (
    DOCUMENT_STATUS_DRAFT, DOCUMENT_STATUS_OBSOLETE,
)


# --------------------------------------------------------------------------
# Incidencias — ck_adhoc_incidents_status
# --------------------------------------------------------------------------

INCIDENT_STATUS_NOT_STARTED: Final[str] = "No Iniciada"
INCIDENT_STATUS_STARTED: Final[str] = "Iniciada"
INCIDENT_STATUS_CLOSED: Final[str] = "Cerrada"

IncidentStatus = Literal["No Iniciada", "Iniciada", "Cerrada"]
INCIDENT_STATUSES: Final[tuple[str, ...]] = ("No Iniciada", "Iniciada", "Cerrada")
INCIDENT_STATUS_DEFAULT: Final[str] = INCIDENT_STATUS_NOT_STARTED


# --------------------------------------------------------------------------
# Eventos de programa — ck_adhoc_program_events_status
# --------------------------------------------------------------------------

PROGRAM_EVENT_STATUS_PLANNED: Final[str] = "Planeado"
PROGRAM_EVENT_STATUS_IN_PROGRESS: Final[str] = "En Proceso"
PROGRAM_EVENT_STATUS_COMPLETED: Final[str] = "Completado"

ProgramEventStatus = Literal["Planeado", "En Proceso", "Completado"]
PROGRAM_EVENT_STATUSES: Final[tuple[str, ...]] = ("Planeado", "En Proceso", "Completado")
PROGRAM_EVENT_STATUS_DEFAULT: Final[str] = PROGRAM_EVENT_STATUS_PLANNED


# --------------------------------------------------------------------------
# Tareas — ck_adhoc_tasks_status
# --------------------------------------------------------------------------

TASK_STATUS_PENDING: Final[str] = "Pendiente"
TASK_STATUS_IN_PROGRESS: Final[str] = "En Proceso"
TASK_STATUS_IN_REVIEW: Final[str] = "En Revisión"
TASK_STATUS_WAITING: Final[str] = "En Espera"
TASK_STATUS_COMPLETED: Final[str] = "Completada"
TASK_STATUS_REJECTED: Final[str] = "Rechazada"

TaskStatus = Literal[
    "Pendiente", "En Proceso", "En Revisión", "En Espera", "Completada", "Rechazada",
]
TASK_STATUSES: Final[tuple[str, ...]] = (
    "Pendiente", "En Proceso", "En Revisión", "En Espera", "Completada", "Rechazada",
)
TASK_STATUS_DEFAULT: Final[str] = TASK_STATUS_PENDING

#: Estados en los que la tarea sigue siendo trabajo del ejecutor. Es el filtro
#: de la rama "tareas_ejecutor" del tablero del dashboard (plan §3.b).
TASK_OPEN_STATUSES: Final[tuple[str, ...]] = (
    TASK_STATUS_PENDING, TASK_STATUS_REJECTED, TASK_STATUS_IN_PROGRESS,
)


# --------------------------------------------------------------------------
# Prioridades — ck_adhoc_tasks_priority == ck_adhoc_incidents_priority
#                                       == ck_adhoc_program_events_priority
# --------------------------------------------------------------------------

PRIORITY_LOW: Final[str] = "Baja"
PRIORITY_MEDIUM: Final[str] = "Media"
PRIORITY_HIGH: Final[str] = "Alta"
PRIORITY_URGENT: Final[str] = "Urgente"

Priority = Literal["Baja", "Media", "Alta", "Urgente"]
PRIORITIES: Final[tuple[str, ...]] = ("Baja", "Media", "Alta", "Urgente")
PRIORITY_DEFAULT: Final[str] = PRIORITY_MEDIUM


# --------------------------------------------------------------------------
# Indicadores — ck_adhoc_indicators_frequency / ck_adhoc_indicator_trackings_color
# --------------------------------------------------------------------------

#: ``adhoc_indicators.frequency`` es ``nullable=True``: el CheckConstraint admite
#: NULL por semántica SQL. El ``''`` que manda el ``<option>`` placeholder del
#: legacy se coacciona a ``None`` (ver ``schemas/common.empty_to_none``).
IndicatorFrequency = Literal["Semanal", "Mensual", "Anual"]
INDICATOR_FREQUENCIES: Final[tuple[str, ...]] = ("Semanal", "Mensual", "Anual")

TRACKING_COLOR_WHITE: Final[str] = "blanco"
TRACKING_COLOR_RED: Final[str] = "rojo"
TRACKING_COLOR_YELLOW: Final[str] = "amarillo"
TRACKING_COLOR_GREEN: Final[str] = "verde"

TrackingColor = Literal["blanco", "rojo", "amarillo", "verde"]
TRACKING_COLORS: Final[tuple[str, ...]] = ("blanco", "rojo", "amarillo", "verde")
TRACKING_COLOR_DEFAULT: Final[str] = TRACKING_COLOR_WHITE

#: Cuántas celdas de seguimiento tiene el tablero según la frecuencia del
#: indicador. Es el rango válido de ``period_index`` (0-based) en el upsert.
TRACKING_PERIODS_BY_FREQUENCY: Final[dict[str, int]] = {
    "Semanal": 52,
    "Mensual": 12,
    "Anual": 1,
}


# --------------------------------------------------------------------------
# Workflow de aprobación
# --------------------------------------------------------------------------

#: ck_adhoc_task_approvals_decision — en minúsculas, a diferencia del resto.
APPROVAL_DECISION_APPROVED: Final[str] = "aprobado"
APPROVAL_DECISION_REJECTED: Final[str] = "rechazado"

ApprovalDecision = Literal["aprobado", "rechazado"]
APPROVAL_DECISIONS: Final[tuple[str, ...]] = ("aprobado", "rechazado")

#: Acciones que acepta ``POST /tasks/{id}/workflow-action``. No hay
#: CheckConstraint detrás (no se persisten), pero el vocabulario es cerrado:
#: viene de ``api_tasks.py::process_task_workflow`` del legacy (plan §10.b).
WORKFLOW_ACTION_FINISH: Final[str] = "terminar"
WORKFLOW_ACTION_REJECT: Final[str] = "rechazar"
WORKFLOW_ACTION_APPROVE: Final[str] = "aprobar"

WorkflowAction = Literal["terminar", "rechazar", "aprobar"]
WORKFLOW_ACTIONS: Final[tuple[str, ...]] = ("terminar", "rechazar", "aprobar")


# --------------------------------------------------------------------------
# Vocabularios de la API (sin respaldo en BD, pero cerrados igual)
# --------------------------------------------------------------------------

#: Discriminador de ``GET /tasks?parent_type=...``. Se corresponde 1:1 con las
#: tres FK excluyentes de ``ck_adhoc_tasks_single_parent``.
TaskParentType = Literal["incident", "program", "document"]
TASK_PARENT_TYPES: Final[tuple[str, ...]] = ("incident", "program", "document")

#: Los cuatro almacenes de ``instance/apps/adhoc/``. El nombre del kind es el
#: nombre del subdirectorio: ver ``services/upload_service.py``.
UploadKind = Literal[
    "documents", "program_events", "task_comments", "indicators", "incidents",
]
UPLOAD_KINDS: Final[tuple[str, ...]] = (
    "documents", "program_events", "task_comments", "indicators", "incidents",
)

#: ``GET /adhoc/reportes/{tipo}`` (plan §4).
ReportType = Literal[
    "area_usuarios", "usuarios_tareas", "usuarios_documentos",
    "documentos_usuarios", "documentos_notas",
]
REPORT_TYPES: Final[tuple[str, ...]] = (
    "area_usuarios", "usuarios_tareas", "usuarios_documentos",
    "documentos_usuarios", "documentos_notas",
)
