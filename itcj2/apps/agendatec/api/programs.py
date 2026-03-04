"""
Programs API v2 — Programas académicos.
Fuente: itcj/apps/agendatec/routes/api/programs_academic.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from itcj2.dependencies import DbSession, CurrentUser
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User

router = APIRouter(tags=["agendatec-programs"])
logger = logging.getLogger(__name__)


# ==================== GET /programs ====================

@router.get("")
def list_programs(
    user: CurrentUser,
    db: DbSession = None,
    q: Optional[str] = Query(None, description="Búsqueda por nombre"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Lista programas académicos con paginación y búsqueda opcional."""
    query = db.query(Program)
    if q and q.strip():
        query = query.filter(Program.name.ilike(f"%{q.strip()}%"))

    total = query.count()
    items = query.order_by(Program.name.asc()).limit(limit).offset(offset).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [{"id": p.id, "name": p.name} for p in items],
    }


# ==================== GET /programs/<program_id>/coordinator ====================

@router.get("/{program_id}/coordinator")
def program_coordinator(
    program_id: int,
    user: CurrentUser,
    db: DbSession = None,
):
    """Obtiene los coordinadores asignados a un programa."""
    rows = (
        db.query(Coordinator, User)
        .join(ProgramCoordinator, ProgramCoordinator.coordinator_id == Coordinator.id)
        .join(User, User.id == Coordinator.user_id)
        .filter(ProgramCoordinator.program_id == program_id)
        .all()
    )

    data = [
        {
            "coordinator_id": c.id,
            "user_id": u.id,
            "full_name": u.full_name,
            "email": c.contact_email or u.email,
            "office_hours": c.office_hours or "",
            "username": getattr(u, "username", None),
        }
        for c, u in rows
    ]
    return {"program_id": program_id, "coordinators": data}
