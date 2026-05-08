"""
Re-exports de schemas de configuración del módulo Helpdesk.
"""
from .priorities import (
    CreatePriorityRequest,
    UpdatePriorityRequest,
    TogglePriorityRequest,
    ReorderPrioritiesRequest,
)

__all__ = [
    "CreatePriorityRequest",
    "UpdatePriorityRequest",
    "TogglePriorityRequest",
    "ReorderPrioritiesRequest",
]
