"""Mundial 2026 API — partidos del día / pasados / próximos (lee Redis)."""
import logging
from typing import Literal

from fastapi import APIRouter, Query

from itcj2.dependencies import CurrentUser, DbSession

router = APIRouter(tags=["core-mundial"])
logger = logging.getLogger("itcj2.mundial")

from itcj2.core.services import mundial_service


@router.get("/matches")
def get_matches(
    user: CurrentUser,
    db: DbSession,
    scope: Literal["today", "past", "upcoming", "all"] = Query("today"),
):
    """Partidos del Mundial por scope. Vacío si el tema no está activo. Nunca 5xx."""
    try:
        if not mundial_service.is_theme_active(db):
            return {"success": True, "data": {"scope": scope, "matches": [], "next_match": None}}
        data = mundial_service.get_matches(scope)
        return {"success": True, "data": data}
    except Exception as exc:
        logger.warning("mundial/matches degradado: %s", exc)
        return {"success": True, "data": {"scope": scope, "matches": [], "next_match": None}}
