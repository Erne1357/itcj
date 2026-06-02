"""
Coordinators API — maint.

CRUD del mapeo coordinador↔área + endpoint de técnicos por área.
Gate: maint.coordinators.api.manage (solo admin).

Rutas montadas bajo /api/maint/v2/coordinators (ver router.py).
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.coordinators import SetCoordinatorAreasRequest

router = APIRouter(tags=["maint-coordinators"])
logger = logging.getLogger(__name__)


# ==================== LISTAR COORDINADORES ====================

@router.get("")
def list_coordinators(
    request: Request,
    user: dict = require_perms("maint", ["maint.coordinators.api.manage"]),
    db: DbSession = None,
):
    """Lista todos los coordinadores (generales + de área) con sus áreas asignadas."""
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    try:
        data = CoordinatorService.list_coordinators(db)
        return {"success": True, "data": data, "total": len(data)}
    except Exception as e:
        logger.error("Error listando coordinadores: %s", e)
        raise HTTPException(status_code=500, detail="Error interno al listar coordinadores")


# ==================== ÁREAS DE UN COORDINADOR ====================

@router.get("/{user_id}/areas")
def get_coordinator_areas(
    user_id: int,
    request: Request,
    user: dict = require_perms("maint", ["maint.coordinators.api.manage"]),
    db: DbSession = None,
):
    """Retorna los códigos de área asignados a un coordinador de área específico."""
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    try:
        areas = CoordinatorService.get_coordinator_areas(db, user_id)
        return {"success": True, "data": {"user_id": user_id, "areas": areas}}
    except Exception as e:
        logger.error("Error obteniendo áreas del coordinador %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Error interno al obtener áreas")


# ==================== ASIGNAR / REEMPLAZAR ÁREAS ====================

@router.put("/{user_id}/areas")
def set_coordinator_areas(
    user_id: int,
    body: SetCoordinatorAreasRequest,
    request: Request,
    user: dict = require_perms("maint", ["maint.coordinators.api.manage"]),
    db: DbSession = None,
):
    """
    Reemplaza completamente el set de áreas del coordinador.
    Enviar lista vacía elimina todas las áreas del usuario.
    """
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    performed_by_id = int(user["sub"])
    try:
        final_areas = CoordinatorService.set_coordinator_areas(
            db=db,
            user_id=user_id,
            area_codes=body.area_codes,
            performed_by_id=performed_by_id,
        )
        return {
            "success": True,
            "message": f"Áreas del coordinador {user_id} actualizadas",
            "data": {"user_id": user_id, "areas": final_areas},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error actualizando áreas del coordinador %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Error interno al actualizar áreas")


# ==================== CATÁLOGO DE ÁREAS (para el board) ====================

@router.get("/areas")
def list_areas_for_board(
    request: Request,
    user: dict = require_perms("maint", ["maint.assignments.page.list"]),
    db: DbSession = None,
):
    """
    Catálogo de áreas técnicas activas, accesible para coordinadores.
    Usado por el tablero de asignación para poblar el filtro de área
    (el endpoint /config/areas es admin-only).
    """
    from itcj2.apps.maint.utils import catalog_cache

    areas = [a for a in catalog_cache.get_areas() if a.get("is_active")]
    return {"success": True, "data": areas, "total": len(areas)}


# ==================== TÉCNICOS POR ÁREA ====================

@router.get("/technicians")
def get_technicians_by_area(
    area_code: str,
    request: Request,
    user: dict = require_perms("maint", ["maint.assignments.page.list"]),
    db: DbSession = None,
):
    """
    Lista técnicos de un área específica.
    Útil para el board de asignación cuando el coordinador quiere filtrar
    candidatos por área. Gate: assignments.page.list (coordinadores + admin).
    """
    from itcj2.apps.maint.services.assignment_service import get_technicians_by_area as _get

    try:
        technicians = _get(db, area_code)
        data = [
            {"user_id": t.id, "name": t.full_name, "email": t.email}
            for t in technicians
        ]
        return {"success": True, "data": data, "total": len(data)}
    except Exception as e:
        logger.error("Error obteniendo técnicos del área %s: %s", area_code, e)
        raise HTTPException(status_code=500, detail="Error interno al obtener técnicos")
