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
from itcj2.apps.maint.schemas.config.areas import (
    CreateArea,
    UpdateArea,
    ToggleArea,
    ReorderAreaItem,
    ReorderAreas,
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
    "CreateArea",
    "UpdateArea",
    "ToggleArea",
    "ReorderAreaItem",
    "ReorderAreas",
]
