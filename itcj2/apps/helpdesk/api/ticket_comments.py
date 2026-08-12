"""
Ticket Comments API v2 — 2 endpoints (with file upload support).
Fuente: itcj/apps/helpdesk/routes/api/tickets/comments.py
"""
import os
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-ticket-comments"])
logger = logging.getLogger(__name__)


@router.get("/{ticket_id}/comments")
def get_comments(
    ticket_id: int,
    user: dict = require_perms("helpdesk", [
        "helpdesk.tickets.api.read.own",
        "helpdesk.tickets.api.read.all",
        "helpdesk.tickets.api.read.subtree",
    ]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.models import Comment

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    can_see_internal = any(r in user_roles for r in ["admin", "secretary", "tech_desarrollo", "tech_soporte"])

    query = db.query(Comment).filter_by(ticket_id=ticket_id)
    if not can_see_internal:
        query = query.filter_by(is_internal=False)

    comments = query.order_by(Comment.created_at.asc()).all()

    return {
        "ticket_id": ticket_id,
        "comments": [c.to_dict() for c in comments],
        "count": len(comments),
    }


@router.post("/{ticket_id}/comments", status_code=201)
async def add_comment(
    ticket_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.comments.api.create"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.services import file_validation_service as fvs
    from itcj2.apps.helpdesk.models import Attachment
    from itcj2.config import get_settings
    from werkzeug.utils import secure_filename

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    s = get_settings()
    UPLOAD_FOLDER = s.HELPDESK_UPLOAD_PATH

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        content = (form.get("content", "") or "").strip()
        is_internal = str(form.get("is_internal", "false")).lower() in ("true", "1")
        files = []
        for key in form:
            if key == "files":
                val = form.getlist("files")
                files = [f for f in val if hasattr(f, "read")]
                break
        if not files:
            file_val = form.get("files")
            if file_val and hasattr(file_val, "read"):
                files = [file_val]
    else:
        data = await request.json()
        content = (data.get("content", "") or "").strip()
        is_internal = data.get("is_internal", False)
        files = []

    if not content:
        raise HTTPException(400, detail={"error": "missing_content", "message": "Se requiere el contenido del comentario"})

    if is_internal:
        can_create_internal = any(r in user_roles for r in ["admin", "secretary", "tech_desarrollo", "tech_soporte"])
        if not can_create_internal:
            raise HTTPException(403, detail={"error": "forbidden_internal", "message": "No tienes permiso para crear notas internas"})

    if len(files) > s.HELPDESK_MAX_COMMENT_FILES:
        raise HTTPException(400, detail={"error": "too_many_files", "message": f"Máximo {s.HELPDESK_MAX_COMMENT_FILES} archivos por comentario"})

    # Pre-validate files
    allowed_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(',')) | set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))
    validated_files = []
    for f in files:
        is_valid, result = fvs.validate_and_get_file_info(f, allowed_extensions=allowed_ext)
        if not is_valid:
            raise HTTPException(400, detail={"error": "invalid_file", "message": f"{f.filename}: {result}"})
        validated_files.append((f, result))

    # Comentar exige poder VER el ticket: el permiso `comments.api.create` lo tiene
    # hasta el rol staff, así que sin este check cualquiera escribe en el ticket de
    # cualquier departamento. Va ANTES de insertar (antes se resolvía después y con
    # check_permissions=False, que no valida nada).
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    comment = ticket_service.add_comment(
        db,
        ticket_id=ticket_id,
        author_id=user_id,
        content=content,
        is_internal=is_internal,
    )

    saved_files = []

    # Calcular el offset de imágenes existentes UNA vez antes del loop, luego
    # incrementar con un contador local para evitar que el query devuelva el
    # mismo número cuando se suben varias imágenes en el mismo request
    # (los inserts no están commiteados hasta después del loop).
    existing_image_count = fvs.get_next_comment_image_number(db, ticket_id) - 1
    img_counter = 0

    for f, info in validated_files:
        try:
            original_filename = secure_filename(f.filename)
            is_img = info["is_image"]
            folder = os.path.join(UPLOAD_FOLDER, "comments", ticket.ticket_number)
            os.makedirs(folder, exist_ok=True)

            if is_img:
                img_counter += 1
                seq = existing_image_count + img_counter
                store_filename = f"{ticket.ticket_number}_{seq}.jpg"
                filepath = os.path.join(folder, store_filename)
                f.file.seek(0)
                compressed, file_size = fvs.compress_image_for_helpdesk(f.file)
                with open(filepath, "wb") as out:
                    out.write(compressed.read())
                mime_type = "image/jpeg"
            else:
                store_filename = original_filename
                counter = 1
                base, ext = os.path.splitext(store_filename)
                while os.path.exists(os.path.join(folder, store_filename)):
                    store_filename = f"{base}_{counter}{ext}"
                    counter += 1
                filepath = os.path.join(folder, store_filename)
                f.file.seek(0)
                with open(filepath, "wb") as out:
                    out.write(f.file.read())
                file_size = info["size"]
                mime_type = f.content_type

            att = Attachment(
                ticket_id=ticket_id,
                uploaded_by_id=user_id,
                attachment_type="comment",
                comment_id=comment.id,
                filename=store_filename,
                original_filename=original_filename,
                filepath=filepath,
                mime_type=mime_type,
                file_size=file_size,
            )
            db.add(att)
            saved_files.append(att)
        except Exception as file_err:
            logger.error(f"Error guardando archivo {f.filename}: {file_err}")

    if saved_files:
        db.commit()

    logger.info(f"Comentario agregado al ticket {ticket_id} ({len(saved_files)} archivos)")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    from itcj2.core.models.user import User
    author = None
    try:
        author = db.get(User, user_id)
        if author and ticket:
            HelpdeskNotificationHelper.notify_comment_added(db, ticket, comment, author)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación: {notif_error}")

    # Sin broadcast de socket aquí a propósito: `notify_comment_added` (llamado
    # arriba) ya emite `ticket_comment_added` — es el único caller de comentarios
    # que puede await-earlo (async), así que exponerlo también aquí duplicaba el
    # evento. Excepción a la regla general del resto de endpoints: para
    # comentarios el broadcast vive en el helper porque `api/comments.py` (el otro
    # caller de `notify_comment_added`) es sync y no puede emitir por su cuenta.

    return {"message": "Comentario agregado exitosamente", "comment": comment.to_dict()}
