"""
Notifications API v2 - Listado, marcado, eliminación de notificaciones.

Reusa NotificationService de itcj/core/services/notification_service.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/notifications", tags=["notifications"])
logger = logging.getLogger("itcj2.notifications")


@router.get("")
@router.get("/")
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    app: str | None = None,
    unread: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    before_id: int | None = None,
):
    """Lista notificaciones del usuario con filtros y paginación."""
    from itcj.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    result = NotificationService.get_notifications(
        user_id=user_id,
        app_name=app,
        unread_only=unread,
        limit=limit,
        offset=offset,
        before_id=before_id,
    )
    return {"status": "ok", "data": result}


@router.get("/unread-counts")
def unread_counts(user: CurrentUser, db: DbSession):
    """Conteos de notificaciones no leídas agrupadas por app."""
    from itcj.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    counts = NotificationService.get_unread_counts_by_app(user_id)
    return {
        "status": "ok",
        "data": {"counts": counts, "total": sum(counts.values())},
    }


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, user: CurrentUser, db: DbSession):
    """Marca una notificación como leída."""
    from itcj.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    success = NotificationService.mark_read(notification_id, user_id)
    if not success:
        raise HTTPException(404, detail="not_found")

    db.commit()
    return {"status": "ok"}


@router.patch("/mark-all-read")
def mark_all_read(user: CurrentUser, db: DbSession, app: str | None = None):
    """Marca todas las notificaciones como leídas (opcionalmente filtradas por app)."""
    from itcj.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    count = NotificationService.mark_all_read(user_id, app)
    db.commit()
    return {"status": "ok", "count": count}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, user: CurrentUser, db: DbSession):
    """Elimina una notificación."""
    from itcj.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    success = NotificationService.delete_notification(notification_id, user_id)
    if not success:
        raise HTTPException(404, detail="not_found")

    db.commit()
    return {"status": "ok"}
