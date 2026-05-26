"""
Config API — Orígenes del servicio (maint).

CRUD completo para el catálogo MaintServiceOrigin con auditoría en
MaintConfigChangeLog e invalidación del cache de módulo tras cada escritura.

Rutas reales (montado en /api/maint/v2/config/service-origins):
  GET    /              → lista todos los orígenes (incluye inactivos)
  POST   /              → crea nuevo origen
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
    invalidate_service_origins,
)
from itcj2.apps.maint.api.config._catalog_crud import (
    crud_list,
    crud_create,
    crud_update,
    crud_toggle,
    crud_reorder,
)

router = APIRouter(tags=["maint-config-service-origins"])
logger = logging.getLogger(__name__)

_ENTITY_TYPE = "service_origin"


@router.get("")
def list_service_origins(
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.service_origins.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """Lista todos los orígenes del servicio ordenados por display_order."""
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin
    return crud_list(db, MaintServiceOrigin)


@router.post("", status_code=201)
def create_service_origin(
    request: Request,
    body: CreateCatalogItem,
    user: dict = require_perms("maint", ["maint.config.service_origins.api.update"]),
    db: DbSession = None,
):
    """Crea un nuevo origen del servicio. code debe ser único (se normaliza a UPPER)."""
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin
    return crud_create(
        db=db,
        body=body,
        model_class=MaintServiceOrigin,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_service_origins,
    )


@router.patch("/{item_id}")
def update_service_origin(
    item_id: int,
    request: Request,
    body: UpdateCatalogItem,
    user: dict = require_perms("maint", ["maint.config.service_origins.api.update"]),
    db: DbSession = None,
):
    """Actualiza parcialmente un origen del servicio. El campo `code` nunca se modifica."""
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin
    return crud_update(
        db=db,
        item_id=item_id,
        body=body,
        model_class=MaintServiceOrigin,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_service_origins,
    )


@router.patch("/{item_id}/toggle")
def toggle_service_origin(
    item_id: int,
    request: Request,
    body: ToggleCatalogItem,
    user: dict = require_perms("maint", ["maint.config.service_origins.api.update"]),
    db: DbSession = None,
):
    """Activa o desactiva un origen del servicio. No se puede desactivar el último activo."""
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin
    return crud_toggle(
        db=db,
        item_id=item_id,
        body=body,
        model_class=MaintServiceOrigin,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_service_origins,
    )


@router.put("/reorder")
def reorder_service_origins(
    request: Request,
    body: ReorderCatalog,
    user: dict = require_perms("maint", ["maint.config.service_origins.api.update"]),
    db: DbSession = None,
):
    """Reordena el catálogo de orígenes del servicio en bloque."""
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin
    return crud_reorder(
        db=db,
        body=body,
        model_class=MaintServiceOrigin,
        entity_type=_ENTITY_TYPE,
        user_id=int(user["sub"]),
        request=request,
        invalidate_fn=invalidate_service_origins,
    )
