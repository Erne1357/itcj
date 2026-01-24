# services/__init__.py
"""
Módulo de servicios para AgendaTec.

Este módulo exporta los servicios de lógica de negocio:
- RequestService: Gestión de solicitudes de estudiantes
- admin_change_request_status: Cambio de estado desde admin
"""
from itcj.apps.agendatec.services.request_service import (
    RequestService,
    ServiceResult,
    ValidationResult,
    get_request_service,
)
from itcj.apps.agendatec.services.request_ops import admin_change_request_status

__all__ = [
    "RequestService",
    "ServiceResult",
    "ValidationResult",
    "get_request_service",
    "admin_change_request_status",
]
