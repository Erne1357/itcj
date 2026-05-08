"""
Notifications API v2 - Listado, marcado, eliminación de notificaciones.

Reusa NotificationService de itcj/core/services/notification_service.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import CurrentUser, DbSession
from itcj2.utils import async_broadcast as _async_broadcast

router = APIRouter(prefix="/notifications", tags=["notifications"])
logger = logging.getLogger("itcj2.notifications")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

async def _emit_read_event(user_id: int, counts: dict, total: int) -> None:
    """Emite notification:read al room personal del usuario en /notify.
    Sincroniza dashboard widget + todos los AppNotificationFAB abiertos.
    """
    try:
        from itcj2.sockets.server import sio
        await sio.emit(
            "notification:read",
            {"counts": counts, "total": total},
            to=f"user:{int(user_id)}:notify",
            namespace="/notify",
        )
    except Exception as exc:
        logger.warning("notification:read emit failed for user %s: %s", user_id, exc)


def _push_counts_to_user(db, user_id: int) -> None:
    """Calcula counts agregados y los envía via WS al room del usuario."""
    from itcj2.core.services.notification_service import NotificationService

    counts = NotificationService.get_unread_counts_by_app(db, user_id)
    total = sum(counts.values())
    _async_broadcast(_emit_read_event(user_id, counts, total))


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
    from itcj2.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    result = NotificationService.get_notifications(
        db,
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
    from itcj2.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    counts = NotificationService.get_unread_counts_by_app(db, user_id)
    return {
        "status": "ok",
        "data": {"counts": counts, "total": sum(counts.values())},
    }


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, user: CurrentUser, db: DbSession):
    """Marca una notificación como leída."""
    from itcj2.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    success = NotificationService.mark_read(db, notification_id, user_id)
    if not success:
        raise HTTPException(404, detail="not_found")

    db.commit()
    _push_counts_to_user(db, user_id)
    return {"status": "ok"}


@router.patch("/mark-all-read")
def mark_all_read(user: CurrentUser, db: DbSession, app: str | None = None):
    """Marca todas las notificaciones como leídas (opcionalmente filtradas por app)."""
    from itcj2.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    count = NotificationService.mark_all_read(db, user_id, app)
    db.commit()
    _push_counts_to_user(db, user_id)
    return {"status": "ok", "count": count}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, user: CurrentUser, db: DbSession):
    """Elimina una notificación."""
    from itcj2.core.services.notification_service import NotificationService

    user_id = int(user["sub"])
    success = NotificationService.delete_notification(db, notification_id, user_id)
    if not success:
        raise HTTPException(404, detail="not_found")

    db.commit()
    _push_counts_to_user(db, user_id)
    return {"status": "ok"}
