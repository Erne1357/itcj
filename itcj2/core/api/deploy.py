"""
Deploy API v2 — 1 endpoint.
Recibe notificaciones de cambios en archivos estáticos y emite eventos WebSocket.
Fuente: itcj/core/routes/api/deploy.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from itcj2.config import get_settings

router = APIRouter(tags=["core-deploy"])
logger = logging.getLogger(__name__)


class StaticUpdateBody(BaseModel):
    changed: list[str] = []
    removed: list[str] = []
    deploy_key: Optional[str] = None


@router.post("/static-update")
def notify_static_update(body: StaticUpdateBody):
    """Recibe archivos estáticos modificados y emite evento WebSocket a los clientes.

    Llamado por el script de deploy cuando hay cambios.
    Emite evento `static_update` al namespace `/notify` via Socket.IO.
    """
    settings = get_settings()
    deploy_secret = getattr(settings, "DEPLOY_SECRET", "")

    if deploy_secret and body.deploy_key != deploy_secret:
        raise HTTPException(403, detail={"error": "unauthorized", "message": "Invalid deploy key"})

    if not body.changed and not body.removed:
        return {"ok": True, "notified": 0, "message": "No changes to notify"}

    # Emitir via Socket.IO al namespace /notify
    # Durante la coexistencia Flask/FastAPI, el Socket.IO lo gestiona Flask.
    # En Fase 3 (migración de sockets) se usará el sio ASGI de itcj2/sockets/.
    try:
        from itcj.core.extensions import socketio
        if socketio:
            socketio.emit(
                "static_update",
                {"changed": body.changed, "removed": body.removed},
                namespace="/notify",
            )
            logger.info(
                f"Deploy notification sent: {len(body.changed)} changed, {len(body.removed)} removed"
            )
            return {
                "ok": True,
                "notified": len(body.changed) + len(body.removed),
                "changed": len(body.changed),
                "removed": len(body.removed),
            }
    except (ImportError, Exception):
        pass

    logger.warning("SocketIO not available, deploy notification not sent")
    raise HTTPException(503, detail={"ok": False, "error": "socketio_unavailable", "message": "WebSocket server not available"})
