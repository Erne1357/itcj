"""
Attachments API v2 — 5 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/attachments.py
"""
import os
import uuid
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-attachments"])
logger = logging.getLogger(__name__)


def _get_upload_folder():
    from itcj2.config import get_settings
    return get_settings().HELPDESK_UPLOAD_PATH


@router.post("/ticket/{ticket_id}", status_code=201)
def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    attachment_type: str = Form("ticket"),
    comment_id: int | None = Form(None),
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.services import file_validation_service as fvs
    from itcj2.apps.helpdesk.models import Attachment
    from itcj2.config import get_settings
    from itcj2.apps.helpdesk.utils.timezone_utils import now_local
    from werkzeug.utils import secure_filename

    user_id = int(user["sub"])
    s = get_settings()
    UPLOAD_FOLDER = _get_upload_folder()

    if attachment_type not in ("ticket", "resolution", "comment"):
        raise HTTPException(400, detail={"error": "invalid_type", "message": "attachment_type debe ser ticket, resolution o comment"})

    if attachment_type == "comment" and not comment_id:
        raise HTTPException(400, detail={"error": "missing_comment_id", "message": "comment_id es requerido para adjuntos de comentario"})

    if attachment_type == "ticket":
        allowed_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))
    else:
        allowed_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(',')) | set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

    is_valid, result = fvs.validate_and_get_file_info(file, allowed_extensions=allowed_ext)
    if not is_valid:
        raise HTTPException(400, detail={"error": "invalid_file", "message": result})

    filepath = None
    try:
        ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

        if attachment_type == "resolution":
            existing_count = db.query(Attachment).filter_by(ticket_id=ticket_id, attachment_type="resolution").count()
            if existing_count >= s.HELPDESK_MAX_RESOLUTION_FILES:
                raise HTTPException(400, detail={"error": "limit_reached", "message": f"Máximo {s.HELPDESK_MAX_RESOLUTION_FILES} archivos de resolución"})

        elif attachment_type == "comment" and comment_id:
            existing_count = db.query(Attachment).filter_by(comment_id=comment_id, attachment_type="comment").count()
            if existing_count >= s.HELPDESK_MAX_COMMENT_FILES:
                raise HTTPException(400, detail={"error": "limit_reached", "message": f"Máximo {s.HELPDESK_MAX_COMMENT_FILES} archivos por comentario"})

        original_filename = secure_filename(file.filename)
        extension = result["extension"]
        is_img = result["is_image"]

        if attachment_type == "comment" and is_img:
            seq = fvs.get_next_comment_image_number(db, ticket_id)
            store_filename = f"{ticket.ticket_number}_{seq}.jpg"
            folder = os.path.join(UPLOAD_FOLDER, "comments", ticket.ticket_number)
        elif attachment_type == "resolution":
            store_filename = original_filename
            folder = os.path.join(UPLOAD_FOLDER, "resolutions", ticket.ticket_number)
        elif attachment_type == "comment":
            store_filename = original_filename
            folder = os.path.join(UPLOAD_FOLDER, "comments", ticket.ticket_number)
        else:
            unique = f"{ticket.id}_{now_local().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
            store_filename = f"{unique}.{extension}"
            folder = os.path.join(UPLOAD_FOLDER, str(ticket.id))

        # Ensure unique filename for non-ticket types
        if attachment_type != "ticket":
            base, ext = os.path.splitext(store_filename)
            candidate = store_filename
            counter = 1
            while os.path.exists(os.path.join(folder, candidate)):
                candidate = f"{base}_{counter}{ext}"
                counter += 1
            store_filename = candidate

        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, store_filename)

        mime_type = file.content_type
        file_size = result["size"]

        if is_img:
            try:
                file.file.seek(0)
                compressed, compressed_size = fvs.compress_image_for_helpdesk(file.file)
                with open(filepath, "wb") as f:
                    f.write(compressed.read())
                file_size = compressed_size
                mime_type = "image/jpeg"
            except Exception as e:
                logger.warning(f"No se pudo comprimir imagen: {e}")
                file.file.seek(0)
                with open(filepath, "wb") as f:
                    f.write(file.file.read())
        else:
            file.file.seek(0)
            with open(filepath, "wb") as f:
                f.write(file.file.read())

        attachment = Attachment(
            ticket_id=ticket_id,
            uploaded_by_id=user_id,
            attachment_type=attachment_type,
            comment_id=comment_id if attachment_type == "comment" else None,
            filename=store_filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type=mime_type,
            file_size=file_size,
        )

        db.add(attachment)
        db.commit()

        logger.info(f"Archivo {original_filename} ({attachment_type}) subido al ticket {ticket_id}")
        return {"message": "Archivo subido exitosamente", "attachment": attachment.to_dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al subir archivo al ticket {ticket_id}: {e}")
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        raise


@router.get("/ticket/{ticket_id}")
def list_attachments(
    ticket_id: int,
    type: str | None = None,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.models import Attachment

    user_id = int(user["sub"])
    ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    query = db.query(Attachment).filter_by(ticket_id=ticket_id)
    if type and type in ("ticket", "resolution", "comment"):
        query = query.filter_by(attachment_type=type)

    attachments = query.order_by(Attachment.uploaded_at.desc()).all()
    return {"ticket_id": ticket_id, "count": len(attachments), "attachments": [att.to_dict() for att in attachments]}


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.models import Attachment

    user_id = int(user["sub"])
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, detail={"error": "not_found", "message": "Archivo no encontrado"})

    ticket_service.get_ticket_by_id(db, attachment.ticket_id, user_id, check_permissions=True)

    if not os.path.exists(attachment.filepath):
        raise HTTPException(404, detail={"error": "file_not_found", "message": "El archivo no existe en el servidor"})

    return FileResponse(
        attachment.filepath,
        media_type=attachment.mime_type,
        filename=attachment.original_filename,
    )


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.models import Attachment

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    is_admin = "admin" in user_roles

    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, detail={"error": "not_found", "message": "Archivo no encontrado"})

    if not is_admin and attachment.uploaded_by_id != user_id:
        raise HTTPException(403, detail={"error": "forbidden", "message": "Solo el uploader o admin pueden eliminar el archivo"})

    if os.path.exists(attachment.filepath):
        os.remove(attachment.filepath)

    db.delete(attachment)
    db.commit()

    logger.info(f"Attachment {attachment_id} eliminado por usuario {user_id}")
    return {"message": "Archivo eliminado exitosamente"}


@router.get("/custom-field/{ticket_id}/{field_key}")
def download_custom_field_file(
    ticket_id: int,
    field_key: str,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    if not ticket.custom_fields or field_key not in ticket.custom_fields:
        raise HTTPException(404, detail={"error": "field_not_found", "message": f'El campo "{field_key}" no existe'})

    file_value = ticket.custom_fields[field_key]
    if not isinstance(file_value, str) or not file_value.startswith("/instance/"):
        raise HTTPException(404, detail={"error": "invalid_file_path", "message": "El campo no contiene una ruta de archivo válida"})

    relative_path = file_value.lstrip("/")
    filepath = os.path.join(os.getcwd(), relative_path)

    if not os.path.exists(filepath):
        raise HTTPException(404, detail={"error": "file_not_found", "message": "El archivo ya no está disponible en el servidor."})

    filename = os.path.basename(filepath)
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_types = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    }

    return FileResponse(
        filepath,
        media_type=mime_types.get(ext, "application/octet-stream"),
        filename=filename,
    )
