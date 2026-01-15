"""
Módulo de utilidades para AgendaTec.

Exporta los helpers principales para uso en toda la aplicación.
"""
from .responses import (
    api_error,
    api_success,
    api_created,
    api_deleted,
    api_not_found,
    api_forbidden,
    api_conflict,
    api_validation_error,
    api_service_unavailable,
    api_invalid_payload,
    api_missing_fields,
    api_invalid_status,
    api_period_required,
)

from .period_utils import (
    is_student_window_open,
    get_student_window,
    get_enabled_days_for_active_period,
    fmt_spanish,
)

__all__ = [
    # Responses
    "api_error",
    "api_success",
    "api_created",
    "api_deleted",
    "api_not_found",
    "api_forbidden",
    "api_conflict",
    "api_validation_error",
    "api_service_unavailable",
    "api_invalid_payload",
    "api_missing_fields",
    "api_invalid_status",
    "api_period_required",
    # Period utils
    "is_student_window_open",
    "get_student_window",
    "get_enabled_days_for_active_period",
    "fmt_spanish",
]
