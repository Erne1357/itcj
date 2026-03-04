"""
Comments API v2 — 4 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/comments.py
"""
import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.comments import CreateCommentRequest, UpdateCommentRequest

router = APIRouter(tags=["helpdesk-comments"])
logger = logging.getLogger(__name__)


@router.get("/ticket/{ticket_id}")
def get_ticket_comments(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.models import Comment

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    is_staff = any(r in user_roles for r in ["admin", "secretary", "tech_desarrollo", "tech_soporte"])

    query = db.query(Comment).filter_by(ticket_id=ticket_id)
    if not is_staff:
        query = query.filter_by(is_internal=False)

    comments = query.order_by(Comment.created_at.asc()).all()

    return {
        "ticket_id": ticket_id,
        "count": len(comments),
        "comments": [c.to_dict() for c in comments],
    }


@router.post("/ticket/{ticket_id}", status_code=201)
def create_comment(
    ticket_id: int,
    body: CreateCommentRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.comments.api.create"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    if body.is_internal:
        is_staff = any(r in user_roles for r in ["admin", "secretary", "tech_desarrollo", "tech_soporte"])
        if not is_staff:
            raise HTTPException(403, detail={"error": "forbidden_internal", "message": "No tienes permiso para crear comentarios internos"})

    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    if ticket.status in ("CLOSED", "CANCELED"):
        raise HTTPException(400, detail={"error": "ticket_closed", "message": "No se pueden agregar comentarios a tickets cerrados o cancelados"})

    comment = ticket_service.add_comment(
        db,
        ticket_id=ticket_id,
        author_id=user_id,
        content=body.content.strip(),
        is_internal=body.is_internal,
    )

    logger.info(f"Comentario {'interno' if body.is_internal else 'público'} agregado al ticket {ticket_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    from itcj2.core.models.user import User
    try:
        author = db.get(User, user_id)
        if author:
            HelpdeskNotificationHelper.notify_comment_added(db, ticket, comment, author)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de comentario: {notif_error}")

    return {"message": "Comentario agregado exitosamente", "comment": comment.to_dict()}


@router.patch("/{comment_id}")
def update_comment(
    comment_id: int,
    body: UpdateCommentRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.comments.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Comment
    from itcj2.apps.helpdesk.utils.timezone_utils import now_local

    user_id = int(user["sub"])

    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(404, detail={"error": "not_found", "message": "Comentario no encontrado"})

    if comment.author_id != user_id:
        raise HTTPException(403, detail={"error": "not_author", "message": "Solo el autor puede editar el comentario"})

    if now_local() - comment.created_at > timedelta(minutes=5):
        raise HTTPException(400, detail={"error": "time_expired", "message": "Solo puedes editar comentarios dentro de los primeros 5 minutos"})

    comment.content = body.content.strip()
    comment.updated_at = now_local()
    db.commit()

    logger.info(f"Comentario {comment_id} editado por usuario {user_id}")
    return {"message": "Comentario actualizado", "comment": comment.to_dict()}


@router.delete("/{comment_id}")
def delete_comment(
    comment_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.comments.api.create"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.models import Comment
    from itcj2.apps.helpdesk.utils.timezone_utils import now_local

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    is_admin = "admin" in user_roles

    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(404, detail={"error": "not_found", "message": "Comentario no encontrado"})

    if not is_admin:
        if comment.author_id != user_id:
            raise HTTPException(403, detail={"error": "not_author", "message": "Solo el autor o admin pueden eliminar el comentario"})
        if now_local() - comment.created_at > timedelta(minutes=5):
            raise HTTPException(400, detail={"error": "time_expired", "message": "Solo puedes eliminar comentarios dentro de los primeros 5 minutos"})

    db.delete(comment)
    db.commit()

    logger.info(f"Comentario {comment_id} eliminado por usuario {user_id}")
    return {"message": "Comentario eliminado exitosamente"}
