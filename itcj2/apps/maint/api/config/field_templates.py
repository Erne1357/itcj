"""
Config API — Field Templates por categoría (maint).

Endpoints para leer y actualizar el field_template de una categoría,
usados por el Field Template Builder en la tab de configuración.
"""
import logging

from fastapi import APIRouter, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.categories import UpdateFieldTemplateRequest
from itcj2.apps.maint.services import category_service

router = APIRouter(tags=["maint-config-field-templates"])
logger = logging.getLogger(__name__)


def _category_to_dict(c) -> dict:
    """Serializa una MaintCategory al formato de respuesta de config."""
    return {
        "category_id": c.id,
        "code": c.code,
        "name": c.name,
        "is_active": c.is_active,
        "field_template": c.field_template or [],
    }


@router.get("/{category_id}")
def get_field_template(
    category_id: int,
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.field_templates.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """
    Devuelve la categoría con su field_template actual.
    404 si la categoría no existe.
    """
    category = category_service.get_category_by_id(db, category_id)
    return {"success": True, "data": _category_to_dict(category)}


@router.put("/{category_id}")
def update_field_template(
    category_id: int,
    body: UpdateFieldTemplateRequest,
    request: Request,
    user: dict = require_perms("maint", ["maint.config.field_templates.api.update"]),
    db: DbSession = None,
):
    """
    Reemplaza el field_template completo de la categoría.
    body.fields = [] elimina el template (sin campos dinámicos).
    La validación del schema la realiza validate_field_template dentro del service.
    """
    try:
        category = category_service.update_field_template(db, category_id, body.fields)
        return {"success": True, "data": _category_to_dict(category)}
    except Exception as e:
        # HTTPException de 404/422/500 ya propagada por el service; re-raise directo
        raise
