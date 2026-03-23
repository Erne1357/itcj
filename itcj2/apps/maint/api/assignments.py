"""Assignments API — maint."""
import logging

from fastapi import APIRouter

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.assignments import (
    AssignTechnicianRequest,
    UnassignTechnicianRequest,
)
from itcj2.apps.maint.schemas.technician_areas import (
    AssignTechnicianAreaRequest,
    RemoveTechnicianAreaRequest,
)
from itcj2.apps.maint.services import assignment_service
from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper
from itcj2.apps.maint.services import ticket_service

router = APIRouter(tags=["maint-assignments"])
logger = logging.getLogger(__name__)


# ==================== ASIGNAR TÉCNICOS ====================
@router.post("/{ticket_id}/assign", status_code=200)
async def assign_technicians(
    ticket_id: int,
    body: AssignTechnicianRequest,
    user: dict = require_perms("maint", ["maint.assignments.api.assign"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    result = assignment_service.assign_technicians(
        db=db,
        ticket_id=ticket_id,
        assigned_by_id=user_id,
        user_ids=body.user_ids,
        notes=body.notes,
    )
    ticket = ticket_service.get_ticket_by_id(db, ticket_id)
    for tech_id in body.user_ids:
        MaintNotificationHelper.notify_technician_assigned(db, ticket, tech_id)
    return {"assigned_count": len(result)}


# ==================== REMOVER TÉCNICO ====================
@router.post("/{ticket_id}/unassign")
async def unassign_technician(
    ticket_id: int,
    body: UnassignTechnicianRequest,
    user: dict = require_perms("maint", ["maint.assignments.api.unassign"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    assignment_service.unassign_technician(
        db=db,
        ticket_id=ticket_id,
        unassigned_by_id=user_id,
        user_id=body.user_id,
        reason=body.reason,
    )
    return {"ok": True}


# ==================== ÁREAS DE TÉCNICO ====================
@router.get("/areas/{user_id}")
async def get_technician_areas(
    user_id: int,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    areas = assignment_service.get_technician_areas(db, user_id)
    return {"areas": [a.area_code for a in areas]}


@router.post("/areas", status_code=201)
async def assign_technician_area(
    body: AssignTechnicianAreaRequest,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    admin_id = int(user["sub"])
    area = assignment_service.assign_technician_area(
        db=db,
        assigned_by_id=admin_id,
        user_id=body.user_id,
        area_code=body.area_code,
    )
    return {"ok": True, "area_id": area.id}


@router.delete("/areas")
async def remove_technician_area(
    body: RemoveTechnicianAreaRequest,
    user: dict = require_perms("maint", ["maint.admin.api.areas"]),
    db: DbSession = None,
):
    count = assignment_service.remove_technician_area(
        db=db,
        user_id=body.user_id,
        area_code=body.area_code,
    )
    return {"removed": count}
