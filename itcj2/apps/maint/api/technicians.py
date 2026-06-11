"""Technicians API — maint (gestión de áreas de especialidad)."""
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.services import assignment_service

router = APIRouter(tags=["maint-technicians"])
logger = logging.getLogger(__name__)

# Fallback estático usado si catalog_cache no puede conectar a la BD.
# Debe mantenerse sincronizado con _FALLBACK_AREA_CODES en catalog_cache.py.
VALID_AREAS = {
    'TRANSPORT', 'GENERAL', 'ELECTRICAL', 'CARPENTRY', 'AC', 'GARDENING', 'PAINTING',
}


# ==================== LISTAR TÉCNICOS ====================

@router.get("")
@router.get("/")
async def list_technicians(
    user: dict = require_perms("maint", ["maint.assignments.api.assign"]),
    db: DbSession = None,
):
    """Lista usuarios asignables como ejecutores de tickets: técnicos + coordinadores activos.

    Capta los roles tanto por asignación directa (core_user_app_roles) como por
    PUESTO organizacional (core_position_app_roles) vía _get_users_with_roles_in_app:
    el alta canónica de técnicos es por puesto, y la query anterior (solo UserAppRole)
    los dejaba invisibles (BUG 1-B). El helper ya filtra User.is_active.

    dispatcher queda EXCLUIDO a propósito: enruta tickets, no los ejecuta (auditoría M4).
    Respuesta normalizada a la convención {success, data, total} (BUG 1-A).
    """
    from itcj2.core.services.authz_service import _get_users_with_roles_in_app
    from itcj2.core.models.user import User

    # Ejecutores asignables (D-B / H1): técnicos y coordinadores general / de área.
    PICKER_ROLES = ["tech_maint", "maint_general_coordinator", "maint_area_coordinator"]
    user_ids = _get_users_with_roles_in_app(db, "maint", PICKER_ROLES)

    result = []
    if user_ids:
        users = (
            db.query(User)
            .filter(User.id.in_(user_ids), User.is_active.is_(True))
            .order_by(User.full_name)
            .all()
        )
        for u in users:
            areas = assignment_service.get_technician_areas(db, u.id)
            result.append({
                "id": u.id,
                "name": u.full_name,
                "areas": [
                    {"area_code": a.area_code, "is_primary": a.is_primary}
                    for a in areas
                ],
            })

    return {"success": True, "data": result, "total": len(result)}


# ==================== ÁREAS DE UN TÉCNICO ====================

@router.get("/{user_id}/areas")
async def get_technician_areas(
    user_id: int,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    areas = assignment_service.get_technician_areas(db, user_id)
    return {
        "areas": [
            {"area_code": a.area_code, "is_primary": a.is_primary}
            for a in areas
        ]
    }


# ==================== ASIGNAR ÁREA ====================

@router.post("/{user_id}/areas", status_code=201)
async def assign_area(
    user_id: int,
    body: dict,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    area_code = (body.get("area_code") or "").upper()

    # Validar contra el catálogo dinámico; degradar al set estático si la BD no está disponible.
    from itcj2.apps.maint.utils.catalog_cache import get_area_codes
    valid_codes = get_area_codes() or VALID_AREAS
    if area_code not in valid_codes:
        raise HTTPException(
            status_code=400,
            detail=f'Área inválida. Opciones: {", ".join(sorted(valid_codes))}',
        )

    assigned_by_id = int(user["sub"])
    area = assignment_service.assign_technician_area(db, assigned_by_id, user_id, area_code)
    return {"area_code": area.area_code, "user_id": area.user_id}


# ==================== REMOVER ÁREA ====================

@router.delete("/{user_id}/areas/{area_code}", status_code=200)
async def remove_area(
    user_id: int,
    area_code: str,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    count = assignment_service.remove_technician_area(db, user_id, area_code.upper())
    return {"removed": count}
