"""
Constantes de configuración para AgendaTec.

Este módulo centraliza todas las constantes utilizadas en la aplicación
AgendaTec para evitar valores mágicos dispersos en el código.
"""
from typing import FrozenSet

# =============================================================================
# ESTADOS DE SOLICITUDES (Request)
# =============================================================================

REQUEST_STATUS_PENDING = "PENDING"
REQUEST_STATUS_RESOLVED_SUCCESS = "RESOLVED_SUCCESS"
REQUEST_STATUS_RESOLVED_NOT_COMPLETED = "RESOLVED_NOT_COMPLETED"
REQUEST_STATUS_NO_SHOW = "NO_SHOW"
REQUEST_STATUS_ATTENDED_OTHER_SLOT = "ATTENDED_OTHER_SLOT"
REQUEST_STATUS_CANCELED = "CANCELED"

# Estados que indican que la solicitud fue atendida
REQUEST_ATTENDED_STATES: FrozenSet[str] = frozenset({
    REQUEST_STATUS_RESOLVED_SUCCESS,
    REQUEST_STATUS_RESOLVED_NOT_COMPLETED,
    REQUEST_STATUS_ATTENDED_OTHER_SLOT,
})

# Estados a excluir en consultas de solicitudes pendientes/activas
REQUEST_EXCLUDE_STATES: FrozenSet[str] = frozenset({
    REQUEST_STATUS_CANCELED,
    REQUEST_STATUS_NO_SHOW,
    REQUEST_STATUS_PENDING,
})

# Estados finales (solicitud terminada)
REQUEST_FINAL_STATES: FrozenSet[str] = frozenset({
    REQUEST_STATUS_RESOLVED_SUCCESS,
    REQUEST_STATUS_RESOLVED_NOT_COMPLETED,
    REQUEST_STATUS_NO_SHOW,
    REQUEST_STATUS_ATTENDED_OTHER_SLOT,
    REQUEST_STATUS_CANCELED,
})

# Transiciones válidas desde PENDING
REQUEST_VALID_TRANSITIONS_FROM_PENDING: FrozenSet[str] = frozenset({
    REQUEST_STATUS_RESOLVED_SUCCESS,
    REQUEST_STATUS_RESOLVED_NOT_COMPLETED,
    REQUEST_STATUS_NO_SHOW,
    REQUEST_STATUS_ATTENDED_OTHER_SLOT,
    REQUEST_STATUS_CANCELED,
})

# =============================================================================
# ESTADOS DE CITAS (Appointment)
# =============================================================================

APPOINTMENT_STATUS_SCHEDULED = "SCHEDULED"
APPOINTMENT_STATUS_DONE = "DONE"
APPOINTMENT_STATUS_NO_SHOW = "NO_SHOW"
APPOINTMENT_STATUS_CANCELED = "CANCELED"

APPOINTMENT_VALID_STATUSES: FrozenSet[str] = frozenset({
    APPOINTMENT_STATUS_SCHEDULED,
    APPOINTMENT_STATUS_DONE,
    APPOINTMENT_STATUS_NO_SHOW,
    APPOINTMENT_STATUS_CANCELED,
})

# =============================================================================
# TIPOS DE SOLICITUD
# =============================================================================

REQUEST_TYPE_DROP = "DROP"
REQUEST_TYPE_APPOINTMENT = "APPOINTMENT"

REQUEST_VALID_TYPES: FrozenSet[str] = frozenset({
    REQUEST_TYPE_DROP,
    REQUEST_TYPE_APPOINTMENT,
})

# =============================================================================
# CONFIGURACIÓN DE USUARIOS
# =============================================================================

# Contraseña por defecto para nuevos usuarios staff/coordinadores
# NOTA: En producción, considerar generar contraseñas aleatorias
DEFAULT_STAFF_PASSWORD = "tecno#2K"

# =============================================================================
# PAGINACIÓN
# =============================================================================

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_LIMIT = 20
MAX_LIMIT = 500

# =============================================================================
# SLOTS DE TIEMPO
# =============================================================================

# Duraciones válidas de slots en minutos
VALID_SLOT_MINUTES: FrozenSet[int] = frozenset({5, 10, 15, 20, 30, 60})

# Duración por defecto de un slot en minutos
DEFAULT_SLOT_MINUTES = 10

# =============================================================================
# REDIS - HOLDS DE SLOTS
# =============================================================================

# Prefijos de claves Redis
REDIS_SLOT_HOLD_PREFIX = "slot_hold:"
REDIS_USER_HOLD_PREFIX = "user_hold:"

# Si se permite solo un hold por usuario a la vez
ENFORCE_SINGLE_HOLD_PER_USER = True

# =============================================================================
# NOTIFICACIONES
# =============================================================================

# Tipos de notificación
NOTIFICATION_TYPE_APPOINTMENT_CREATED = "APPOINTMENT_CREATED"
NOTIFICATION_TYPE_APPOINTMENT_CANCELED = "APPOINTMENT_CANCELED"
NOTIFICATION_TYPE_DROP_CREATED = "DROP_CREATED"
NOTIFICATION_TYPE_REQUEST_STATUS_CHANGED = "REQUEST_STATUS_CHANGED"

# Límites de notificaciones
NOTIFICATIONS_DEFAULT_LIMIT = 20
NOTIFICATIONS_MAX_LIMIT = 50

# =============================================================================
# MAPEOS DE TEXTO (UI)
# =============================================================================

# Mapeo de estado a título de notificación
REQUEST_STATUS_TITLE_MAP = {
    REQUEST_STATUS_RESOLVED_SUCCESS: "Tu solicitud fue atendida y resuelta",
    REQUEST_STATUS_RESOLVED_NOT_COMPLETED: "Tu solicitud fue atendida pero no se resolvió",
    REQUEST_STATUS_NO_SHOW: "Marcado como no asistió",
    REQUEST_STATUS_ATTENDED_OTHER_SLOT: "Asististe en otro horario",
    REQUEST_STATUS_CANCELED: "Tu solicitud fue cancelada",
}

# Mapeo de tipo de solicitud a etiqueta
REQUEST_TYPE_LABEL_MAP = {
    REQUEST_TYPE_APPOINTMENT: "CITA",
    REQUEST_TYPE_DROP: "BAJA",
}

# =============================================================================
# ENCUESTAS
# =============================================================================

# Estados válidos para enviar encuesta (atendidos pero no cancelados/no show)
SURVEY_ELIGIBLE_STATES: FrozenSet[str] = REQUEST_ATTENDED_STATES

# Límite por defecto para envío de encuestas
SURVEY_DEFAULT_BATCH_SIZE = 200

# =============================================================================
# REPORTES
# =============================================================================

# Límite de registros para reportes Excel
REPORT_MAX_ROWS = 10000

# Formato de nombre de archivo para exportaciones
REPORT_FILENAME_FORMAT = "solicitudes_{timestamp}.xlsx"
