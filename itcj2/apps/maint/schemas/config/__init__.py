"""Schemas de configuración del módulo maint."""
from itcj2.apps.maint.schemas.config.priorities import (
    CreatePriority,
    UpdatePriority,
    TogglePriority,
    ReorderItem,
    ReorderPriorities,
)
from itcj2.apps.maint.schemas.config.catalogs import (
    CreateCatalogItem,
    UpdateCatalogItem,
    ToggleCatalogItem,
    ReorderCatalogItem,
    ReorderCatalog,
)

__all__ = [
    "CreatePriority",
    "UpdatePriority",
    "TogglePriority",
    "ReorderItem",
    "ReorderPriorities",
    "CreateCatalogItem",
    "UpdateCatalogItem",
    "ToggleCatalogItem",
    "ReorderCatalogItem",
    "ReorderCatalog",
]
