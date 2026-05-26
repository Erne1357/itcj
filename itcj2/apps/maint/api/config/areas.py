"""
Config API — Áreas técnicas (maint).

CRUD completo para el catálogo MaintArea con auditoría en MaintConfigChangeLog
e invalidación del cache de módulo tras cada escritura.

Rutas reales (montado en /api/maint/v2/config/areas):
  GET    /              → lista todas las áreas
  POST   /              → crea nueva área
  PATCH  /{area_id}     → actualiza parcialmente (sin cambiar code)
  PATCH  /{area_id}/toggle → activa/desactiva (avisa si hay técnicos enlazados)
  PUT    /reorder       → reordena el listado
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.config.areas import (
    CreateArea,
    UpdateArea,
    ToggleArea,
    ReorderAreas,
)
from itcj2.apps.maint.services.config_audit_service import log_config_change, client_ip
from itcj2.apps.maint.utils.catalog_cache import invalidate_areas

router = APIRouter(tags=["maint-config-areas"])
logger = logging.getLogger(__name__)


# ==================== HELPERS ====================

def _area_to_dict(a) -> dict:
    return {
        "id": a.id,
        "code": a.code,
        "label": a.label,
        "icon": a.icon,
        "color": a.color,
        "description": a.description,
        "display_order": a.display_order,
        "is_active": a.is_active,
    }


def _count_technicians_for_area(db, area_code: str) -> int:
    """Cuenta cuántos técnicos tienen asignada esta área (por code string)."""
    from itcj2.apps.maint.models.technician_area import MaintTechnicianArea
    return (
        db.query(MaintTechnicianArea)
        .filter(MaintTechnicianArea.area_code == area_code)
        .count()
    )


# ==================== ENDPOINTS ====================

@router.get("")
def list_areas(
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.areas.api.read",
        "maint.admin.api.areas",        # admins de áreas también pueden ver
        "maint.admin.api.categories",   # admins de config general también ven
    ]),
    db: DbSession = None,
):
    """Lista todas las áreas técnicas ordenadas por display_order."""
    from itcj2.apps.maint.models.area import MaintArea

    areas = (
        db.query(MaintArea)
        .order_by(MaintArea.display_order)
        .all()
    )
    return {
        "success": True,
        "data": [_area_to_dict(a) for a in areas],
        "total": len(areas),
    }


@router.post("", status_code=201)
def create_area(
    request: Request,
    body: CreateArea,
    user: dict = require_perms("maint", ["maint.config.areas.api.update"]),
    db: DbSession = None,
):
    """Crea una nueva área técnica. code debe ser único (se normaliza a UPPER)."""
    from itcj2.apps.maint.models.area import MaintArea

    # Verificar unicidad de code
    existing = db.query(MaintArea).filter(MaintArea.code == body.code).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un área con code '{body.code}'",
        )

    area = MaintArea(
        code=body.code,
        label=body.label,
        icon=body.icon,
        color=body.color,
        description=body.description,
        display_order=body.display_order if body.display_order is not None else 0,
        is_active=True,
    )
    db.add(area)
    db.flush()  # Obtener id antes del commit

    after = _area_to_dict(area)
    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="area",
        entity_id=area.id,
        action="create",
        before=None,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(area)
        invalidate_areas()
        logger.info(f"Área '{area.code}' creada por usuario {user['sub']}")
        return {"success": True, "data": _area_to_dict(area)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error creando área: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al crear área")


@router.patch("/{area_id}")
def update_area(
    area_id: int,
    request: Request,
    body: UpdateArea,
    user: dict = require_perms("maint", ["maint.config.areas.api.update"]),
    db: DbSession = None,
):
    """Actualiza parcialmente un área técnica. El campo `code` nunca se modifica."""
    from itcj2.apps.maint.models.area import MaintArea

    area = db.get(MaintArea, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")

    before = _area_to_dict(area)

    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(area, key, val)

    after = _area_to_dict(area)
    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="area",
        entity_id=area_id,
        action="update",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(area)
        invalidate_areas()
        logger.info(f"Área {area_id} actualizada por usuario {user['sub']}")
        return {"success": True, "data": _area_to_dict(area)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error actualizando área {area_id}: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al actualizar área")


@router.patch("/{area_id}/toggle")
def toggle_area(
    area_id: int,
    request: Request,
    body: ToggleArea,
    user: dict = require_perms("maint", ["maint.config.areas.api.update"]),
    db: DbSession = None,
):
    """
    Activa o desactiva un área técnica.
    No se puede desactivar la última área activa.
    Se permite desactivar aunque haya técnicos con esa área (soft); en ese caso
    la respuesta incluye un campo `warning` con el conteo de técnicos afectados.
    """
    from itcj2.apps.maint.models.area import MaintArea

    area = db.get(MaintArea, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")

    warning = None

    if not body.is_active:
        # Regla: debe quedar al menos una activa
        active_count = db.query(MaintArea).filter(
            MaintArea.is_active == True  # noqa: E712
        ).count()
        if active_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Debe existir al menos un área activa",
            )
        # Aviso si hay técnicos que la usan (no bloquea, es informativo)
        tech_count = _count_technicians_for_area(db, area.code)
        if tech_count > 0:
            warning = (
                f"{tech_count} técnico(s) tienen asignada esta área. "
                "El enlace es informativo; la desactivación no los afecta automáticamente."
            )

    before = _area_to_dict(area)
    area.is_active = body.is_active
    after = _area_to_dict(area)

    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="area",
        entity_id=area_id,
        action="toggle",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(area)
        invalidate_areas()
        estado = "activada" if body.is_active else "desactivada"
        logger.info(f"Área {area_id} {estado} por usuario {user['sub']}")
        response: dict = {"success": True, "data": _area_to_dict(area)}
        if warning:
            response["warning"] = warning
        return response
    except Exception as exc:
        db.rollback()
        logger.error(f"Error en toggle de área {area_id}: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al cambiar estado del área")


@router.put("/reorder")
def reorder_areas(
    request: Request,
    body: ReorderAreas,
    user: dict = require_perms("maint", ["maint.config.areas.api.update"]),
    db: DbSession = None,
):
    """Reordena el catálogo de áreas técnicas en bloque."""
    from itcj2.apps.maint.models.area import MaintArea

    if not body.order:
        raise HTTPException(status_code=400, detail="La lista de orden no puede estar vacía")

    before_snapshot = []
    for item in body.order:
        a = db.get(MaintArea, item.id)
        if not a:
            raise HTTPException(status_code=404, detail=f"Área con id={item.id} no encontrada")
        before_snapshot.append({"id": a.id, "code": a.code, "display_order": a.display_order})
        a.display_order = item.display_order

    after_snapshot = [{"id": i.id, "display_order": i.display_order} for i in body.order]

    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="area",
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip=client_ip(request),
    )

    try:
        db.commit()
        invalidate_areas()
        logger.info(f"Áreas reordenadas por usuario {user['sub']}")
        return {"success": True}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error reordenando áreas: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al reordenar áreas")
