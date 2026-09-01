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

router = APIRouter(tags=["prorrogas_tec-programs"])
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

