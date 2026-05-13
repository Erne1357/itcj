"""
Comments API — maint.

Acepta dos Content-Types:
  - application/json  → comportamiento original (CreateCommentRequest)
  - multipart/form-data → campos: content (str), is_internal (bool-string),
                          files (0..N UploadFile)

Los callers JSON existentes no se ven afectados: si el header Content-Type
no contiene "multipart", se delega al path JSON original.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import List, Optional

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.comments import CreateCommentRequest
from itcj2.apps.maint.services import ticket_service
from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

router = APIRouter(tags=["maint-comments"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# POST /{ticket_id}/comments — JSON path (original)
# ─────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/comments", status_code=201)
async def add_comment(
    ticket_id: int,
    request: Request,
    user: dict = require_perms("maint", ["maint.comments.api.create"]),
    db: DbSession = None,
):
    """
    Crea un comentario en el ticket.

    Detecta automáticamente si la petición es JSON o multipart:
    - JSON:      body con campos `content` e `is_internal`
    - Multipart: campos de formulario `content`, `is_internal`, y archivos `files`

    Los adjuntos del multipart se guardan usando la misma lógica que
    POST /tickets/{id}/attachments con attachment_type='comment'.
    """
    user_id = int(user["sub"])
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        return await _add_comment_multipart(
            request=request,
            ticket_id=ticket_id,
            user_id=user_id,
            db=db,
        )

    # --- JSON path ---
    body_bytes = await request.body()
    import json as _json
    try:
        raw = _json.loads(body_bytes)
    except Exception:
        raise HTTPException(400, detail="Cuerpo JSON inválido")

    body = CreateCommentRequest(**raw)

    if body.is_internal:
        from itcj2.core.services.authz_service import get_user_permissions_for_app
        is_admin_global = user.get("role") == "admin"
        user_perms = get_user_permissions_for_app(db, user_id, "maint", include_positions=True)
        if not is_admin_global and "maint.comments.api.internal" not in user_perms:
            raise HTTPException(
                status_code=403,
                detail="Requiere permiso: maint.comments.api.internal",
            )

    comment = ticket_service.add_comment(
        db=db,
        ticket_id=ticket_id,
        author_id=user_id,
        content=body.content,
        is_internal=body.is_internal,
    )
    ticket = ticket_service.get_ticket_by_id(db, ticket_id)
    try:
        MaintNotificationHelper.notify_comment_added(db, ticket, comment, user_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_comment_added failed for ticket %s: %s", ticket.id, exc)
    return {"comment_id": comment.id, "ok": True}


async def _add_comment_multipart(
    request: Request,
    ticket_id: int,
    user_id: int,
    db,
):
    """
    Procesa la ruta multipart: extrae campos del formulario, crea el
    comentario y luego guarda cada archivo adjunto.
    """
    from itcj2.apps.maint.api.attachments import _save_attachment_file

    form = await request.form()

    content = form.get("content", "")
    if not content or len(content.strip()) < 3:
        raise HTTPException(
            400,
            detail={"error": "invalid_content", "message": "El contenido debe tener al menos 3 caracteres"},
        )

    raw_internal = form.get("is_internal", "false")
    is_internal = str(raw_internal).lower() in ("true", "1", "yes")

    if is_internal:
        from itcj2.core.services.authz_service import get_user_permissions_for_app
        user = getattr(request.state, "current_user", None) or {}
        is_admin_global = user.get("role") == "admin"
        user_perms = get_user_permissions_for_app(db, user_id, "maint", include_positions=True)
        if not is_admin_global and "maint.comments.api.internal" not in user_perms:
            raise HTTPException(
                status_code=403,
                detail="Requiere permiso: maint.comments.api.internal",
            )

    # Crear comentario primero
    comment = ticket_service.add_comment(
        db=db,
        ticket_id=ticket_id,
        author_id=user_id,
        content=content.strip(),
        is_internal=is_internal,
    )
    ticket = ticket_service.get_ticket_by_id(db, ticket_id)

    # Guardar archivos adjuntos (si los hay)
    files = form.getlist("files")
    saved_attachments = []
    errors = []

    for upload in files:
        if not hasattr(upload, "filename") or not upload.filename:
            continue
        try:
            att = _save_attachment_file(
                db=db,
                ticket=ticket,
                file=upload,
                attachment_type="comment",
                user_id=user_id,
                comment_id=comment.id,
            )
            saved_attachments.append(att.to_dict())
        except HTTPException as exc:
            # Registrar el error pero no abortar los demás archivos
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            errors.append({"filename": upload.filename, **detail})
        except Exception as exc:
            logger.error(f"Error inesperado al guardar adjunto de comentario: {exc}")
            errors.append({"filename": upload.filename, "message": "Error interno al guardar el archivo"})

    try:
        MaintNotificationHelper.notify_comment_added(db, ticket, comment, user_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_comment_added (multipart) failed for ticket %s: %s", ticket.id, exc)

    return JSONResponse(
        status_code=201,
        content={
            "comment_id": comment.id,
            "ok": True,
            "attachments": saved_attachments,
            "attachment_errors": errors,
        },
    )
