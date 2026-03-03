"""
Mobile API v2 — 2 endpoints (dashboard móvil).
Fuente: itcj/core/routes/api/mobile.py
"""
import logging

from fastapi import APIRouter
from itcj2.dependencies import DbSession, CurrentUser

router = APIRouter(tags=["core-mobile"])
logger = logging.getLogger(__name__)


@router.get("/apps")
def get_mobile_apps(
    user: CurrentUser,
    db: DbSession = None,
):
    """Apps habilitadas para móvil según permisos del usuario."""
    from itcj2.core.services import mobile_service as svc

    user_id = int(user["sub"])
    apps = svc.get_mobile_apps_for_user(db, user_id)
    user_type = svc.get_user_type(db, user_id)
    return {"status": "ok", "data": {"apps": apps, "user_type": user_type}}


@router.get("/user-type")
def get_user_type(
    user: CurrentUser,
    db: DbSession = None,
):
    """Tipo de usuario: 'student' o 'staff'."""
    from itcj2.core.services import mobile_service as svc

    return {"status": "ok", "data": {"user_type": svc.get_user_type(db, int(user["sub"]))}}
