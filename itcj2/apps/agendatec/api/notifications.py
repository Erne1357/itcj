"""
Notifications API v2 — Notificaciones de AgendaTec.
Fuente: itcj/apps/agendatec/routes/api/notifications.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, CurrentUser
from itcj2.core.models.notification import Notification

router = APIRouter(tags=["agendatec-notifications"])
logger = logging.getLogger(__name__)

_MAX_LIMIT = 50
_DEFAULT_LIMIT = 20


# ==================== GET / ====================

@router.get("")
def list_notifications(
    unread: bool = Query(False, description="Solo no leídas"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    before_id: Optional[int] = Query(None),
    user: dict = CurrentUser,
    db: DbSession = None,
):
    """Lista notificaciones del usuario autenticado."""
    uid = int(user["sub"])

    q = db.query(Notification).filter(Notification.user_id == uid)
    if unread:
        q = q.filter(Notification.is_read == False)
    if before_id:
        q = q.filter(Notification.id < before_id)

    items = q.order_by(Notification.id.desc()).limit(limit).all()
    return {"items": [n.to_dict() for n in items]}


# ==================== PATCH /<notif_id>/read ====================

@router.patch("/{notif_id}/read")
def mark_read(
    notif_id: int,
    user: dict = CurrentUser,
    db: DbSession = None,
):
    """Marca una notificación como leída."""
    uid = int(user["sub"])
    n = db.query(Notification).filter_by(id=notif_id, user_id=uid).first()
    if not n:
        raise HTTPException(status_code=404, detail="not_found")

    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now()
        db.commit()
    return {"ok": True}


# ==================== PATCH /read-all ====================

@router.patch("/read-all")
def mark_all_read(
    user: dict = CurrentUser,
    db: DbSession = None,
):
    """Marca todas las notificaciones del usuario como leídas."""
    uid = int(user["sub"])
    db.query(Notification).filter_by(user_id=uid, is_read=False).update(
        {"is_read": True, "read_at": datetime.now()},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True}
