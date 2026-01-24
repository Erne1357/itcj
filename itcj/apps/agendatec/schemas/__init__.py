# schemas/__init__.py
"""
Módulo de schemas de validación para AgendaTec.

Este módulo exporta los schemas Pydantic para validación de datos:
- RequestSchemas: Validación de solicitudes
- SlotSchemas: Validación de slots
"""
from itcj.apps.agendatec.schemas.requests import (
    AdminRequestFilterSchema,
    CreateAppointmentRequestSchema,
    CreateDropRequestSchema,
    CreateRequestSchema,
    RequestType,
    UpdateRequestStatusSchema,
)
from itcj.apps.agendatec.schemas.slots import (
    CreateSlotSchema,
    DayConfigSchema,
    SlotFilterSchema,
    SlotHoldSchema,
)

__all__ = [
    # Requests
    "AdminRequestFilterSchema",
    "CreateAppointmentRequestSchema",
    "CreateDropRequestSchema",
    "CreateRequestSchema",
    "RequestType",
    "UpdateRequestStatusSchema",
    # Slots
    "CreateSlotSchema",
    "DayConfigSchema",
    "SlotFilterSchema",
    "SlotHoldSchema",
]
