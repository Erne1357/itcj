"""Schemas de configuración del módulo maint."""
from itcj2.apps.maint.schemas.config.priorities import (
    CreatePriority,
    UpdatePriority,
    TogglePriority,
    ReorderItem,
    ReorderPriorities,
)

__all__ = [
    "CreatePriority",
    "UpdatePriority",
    "TogglePriority",
    "ReorderItem",
    "ReorderPriorities",
]
