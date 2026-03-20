"""Comments API — maint."""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.comments import CreateCommentRequest
from itcj2.apps.maint.services import ticket_service

router = APIRouter(tags=["maint-comments"])
logger = logging.getLogger(__name__)


@router.post("/{ticket_id}/comments", status_code=201)
async def add_comment(
    ticket_id: int,
    body: CreateCommentRequest,
    user: dict = require_perms("maint", ["maint.comments.api.create"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])

    # Comentarios internos requieren permiso adicional
    if body.is_internal:
        user_perms_dep = require_perms("maint", ["maint.comments.api.internal"])
        user_roles = set(user_roles_in_app(db, user_id, "maint"))
        if not (user_roles & {'admin', 'dispatcher', 'tech_maint'}):
            raise HTTPException(
                status_code=403,
                detail="Los comentarios internos son exclusivos para el staff de mantenimiento",
            )

    comment = ticket_service.add_comment(
        db=db,
        ticket_id=ticket_id,
        author_id=user_id,
        content=body.content,
        is_internal=body.is_internal,
    )
    return {"comment_id": comment.id, "ok": True}
