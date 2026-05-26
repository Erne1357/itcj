"""
Config API — Tipos de mantenimiento (maint).

CRUD completo para el catálogo MaintMaintenanceType con auditoría en
MaintConfigChangeLog e invalidación del cache de módulo tras cada escritura.

Rutas reales (montado en /api/maint/v2/config/maint-types):
  GET    /              → lista todos los tipos (incluye inactivos)
  POST   /              → crea nuevo tipo
  PATCH  /{item_id}     → actualiza parcialmente (sin cambiar code)
  PATCH  /{item_id}/toggle → activa/desactiva
  PUT    /reorder       → reordena el listado
"""
import logging

from fastapi import APIRouter, Request

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.config.catalogs import (
    CreateCatalogItem,
    UpdateCatalogItem,
    ToggleCatalogItem,
    ReorderCatalog,
)
from itcj2.apps.maint.utils.catalog_cache import (
    invalidate_maint_types,
)
from itcj2.apps.maint.api.config._catalog_crud import (
    crud_list,
    crud_create,
    crud_update,
    crud_toggle,
    crud_reorder,
)

router = APIRouter(tags=["maint-config-maint-types"])
logger = logging.getLogger(__name__)

_ENTITY_TYPE = "maint_type"


@router.get("")
def list_maint_types(
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.maint_types.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """Lista todos los tipos de mantenimiento ordenados por display_order."""
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType
    return crud_list(db, MaintMaintenanceType)


@router.post("", status_code=201)
def create_maint_type(
    request: Request,
    body: CreateCatalogItem,
    user: dict = require_perms("maint", ["maint.config.maint_types.api.update"]),
    db: DbSession = None,
):
    """Crea un nuevo tipo de mantenimiento. code debe ser único (se normaliza a UPPER)."""
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType
    return crud_create(
        db=db,
        body=body,
        model_class=MaintMaintenanceType,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_maint_types,
    )


@router.patch("/{item_id}")
def update_maint_type(
    item_id: int,
    request: Request,
    body: UpdateCatalogItem,
    user: dict = require_perms("maint", ["maint.config.maint_types.api.update"]),
    db: DbSession = None,
):
    """Actualiza parcialmente un tipo de mantenimiento. El campo `code` nunca se modifica."""
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType
    return crud_update(
        db=db,
        item_id=item_id,
        body=body,
        model_class=MaintMaintenanceType,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_maint_types,
    )


@router.patch("/{item_id}/toggle")
def toggle_maint_type(
    item_id: int,
    request: Request,
    body: ToggleCatalogItem,
    user: dict = require_perms("maint", ["maint.config.maint_types.api.update"]),
    db: DbSession = None,
):
    """Activa o desactiva un tipo de mantenimiento. No se puede desactivar el último activo."""
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType
    return crud_toggle(
        db=db,
        item_id=item_id,
        body=body,
        model_class=MaintMaintenanceType,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_maint_types,
    )


@router.put("/reorder")
def reorder_maint_types(
    request: Request,
    body: ReorderCatalog,
    user: dict = require_perms("maint", ["maint.config.maint_types.api.update"]),
    db: DbSession = None,
):
    """Reordena el catálogo de tipos de mantenimiento en bloque."""
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType
    return crud_reorder(
        db=db,
        body=body,
        model_class=MaintMaintenanceType,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_maint_types,
    )
