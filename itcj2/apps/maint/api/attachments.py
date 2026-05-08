"""
Attachments API — maint app.

Endpoints:
    POST   /tickets/{ticket_id}/attachments
    GET    /tickets/{ticket_id}/attachments
    GET    /attachments/{attachment_id}/download
    DELETE /attachments/{attachment_id}

Semántica de purga: el archivo físico se elimina pero la fila se conserva
(is_purged=True, filepath=None) para trazabilidad de auditoría.
La eliminación manual por el uploader/admin elimina fila Y archivo.
"""
import os
import uuid
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-attachments"])
logger = logging.getLogger(__name__)


def _get_settings():
    from itcj2.config import get_settings
    return get_settings()


def _resolve_folder(upload_path: str, attachment_type: str, ticket) -> str:
    """Devuelve la carpeta de destino según el tipo de adjunto."""
    if attachment_type == "ticket":
        return os.path.join(upload_path, str(ticket.id))
    elif attachment_type == "resolution":
        return os.path.join(upload_path, "resolutions", ticket.ticket_number)
    else:  # comment
        return os.path.join(upload_path, "comments", ticket.ticket_number)


def _unique_filename(folder: str, base_name: str) -> str:
    """Añade sufijo _2, _3, … si el nombre de archivo ya existe en la carpeta."""
    base, ext = os.path.splitext(base_name)
    candidate = base_name
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        counter += 1
        candidate = f"{base}_{counter}{ext}"
    return candidate


def _save_attachment_file(
    db,
    ticket,
    file: UploadFile,
    attachment_type: str,
    user_id: int,
    comment_id: int | None = None,
):
    """
    Valida, almacena y persiste un adjunto en BD.

    Retorna la instancia MaintAttachment creada o lanza HTTPException.
    Limpia el archivo parcial si el commit falla.
    """
    from itcj2.apps.maint.models.attachment import MaintAttachment
    from itcj2.apps.maint.models.action_log import MaintTicketActionLog
    from itcj2.apps.helpdesk.services import file_validation_service as fvs
    from itcj2.apps.maint.utils.timezone_utils import now_local
    from werkzeug.utils import secure_filename

    s = _get_settings()
    upload_path = s.MAINT_UPLOAD_PATH

    img_exts = set(s.MAINT_ALLOWED_IMAGE_EXTENSIONS.split(","))
    doc_exts = set(s.MAINT_ALLOWED_DOC_EXTENSIONS.split(","))

    if attachment_type == "ticket":
        allowed_ext = img_exts
    else:
        allowed_ext = img_exts | doc_exts

    # --- Validación de extensión y magic bytes (sin límite de tamaño aquí;
    #     lo verificamos después de conocer la extensión) ---
    is_valid, result = fvs.validate_and_get_file_info(
        file, allowed_extensions=allowed_ext, max_size=s.MAINT_MAX_PDF_SIZE
    )
    if not is_valid:
        raise HTTPException(
            400,
            detail={"error": "invalid_file", "message": result},
        )

    extension = result["extension"]
    is_img = result["is_image"]
    file_size = result["size"]

    # Aplicar límite diferenciado: imágenes 3 MB, PDFs 10 MB
    size_limit = s.MAINT_MAX_FILE_SIZE if is_img else s.MAINT_MAX_PDF_SIZE
    if file_size > size_limit:
        limit_mb = size_limit // (1024 * 1024)
        raise HTTPException(
            400,
            detail={
                "error": "file_too_large",
                "message": f"El archivo excede el límite de {limit_mb} MB",
            },
        )

    # --- Límites por tipo ---
    if attachment_type == "resolution":
        existing = (
            db.query(MaintAttachment)
            .filter_by(ticket_id=ticket.id, attachment_type="resolution", is_purged=False)
            .count()
        )
        if existing >= s.MAINT_MAX_RESOLUTION_FILES:
            raise HTTPException(
                400,
                detail={
                    "error": "limit_reached",
                    "message": f"Máximo {s.MAINT_MAX_RESOLUTION_FILES} archivos de resolución por ticket",
                },
            )

    elif attachment_type == "comment" and comment_id:
        existing = (
            db.query(MaintAttachment)
            .filter_by(comment_id=comment_id, attachment_type="comment", is_purged=False)
            .count()
        )
        if existing >= s.MAINT_MAX_COMMENT_FILES:
            raise HTTPException(
                400,
                detail={
                    "error": "limit_reached",
                    "message": f"Máximo {s.MAINT_MAX_COMMENT_FILES} archivos por comentario",
                },
            )

    # --- Nombre y carpeta ---
    original_filename = secure_filename(file.filename)
    folder = _resolve_folder(upload_path, attachment_type, ticket)

    if attachment_type == "ticket":
        ts = now_local().strftime("%Y%m%d%H%M%S")
        uid = uuid.uuid4().hex[:8]
        store_filename = f"{ticket.id}_{ts}_{uid}.{extension}"
    else:
        store_filename = _unique_filename(folder, original_filename)

    filepath = None
    try:
        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, store_filename)

        mime_type = file.content_type or "application/octet-stream"

        if is_img:
            try:
                file.file.seek(0)
                compressed, compressed_size = fvs.compress_image_for_helpdesk(file.file)
                with open(filepath, "wb") as out:
                    out.write(compressed.read())
                file_size = compressed_size
                mime_type = "image/jpeg"
            except Exception as exc:
                logger.warning(f"No se pudo comprimir imagen {original_filename}: {exc}")
                file.file.seek(0)
                with open(filepath, "wb") as out:
                    out.write(file.file.read())
        else:
            file.file.seek(0)
            with open(filepath, "wb") as out:
                out.write(file.file.read())

        att = MaintAttachment(
            ticket_id=ticket.id,
            uploaded_by_id=user_id,
            attachment_type=attachment_type,
            comment_id=comment_id if attachment_type == "comment" else None,
            filename=store_filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type=mime_type,
            file_size=file_size,
        )
        db.add(att)
        db.flush()  # obtener att.id antes del commit

        log_entry = MaintTicketActionLog(
            ticket_id=ticket.id,
            action="ATTACHMENT_ADDED",
            performed_by_id=user_id,
            detail={
                "attachment_id": att.id,
                "type": attachment_type,
                "filename": original_filename,
            },
        )
        db.add(log_entry)
        db.commit()
        db.refresh(att)
        return att

    except HTTPException:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        raise
    except Exception as exc:
        db.rollback()
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        logger.error(f"Error al guardar adjunto para ticket {ticket.id}: {exc}")
        raise HTTPException(500, detail="Error interno al guardar el archivo")


# ─────────────────────────────────────────────────────────────
# POST /tickets/{ticket_id}/attachments
# ─────────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/attachments", status_code=201)
def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    attachment_type: str = Form("ticket"),
    comment_id: int | None = Form(None),
    user: dict = require_perms("maint", ["maint.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.maint.services import ticket_service

    user_id = int(user["sub"])

    if attachment_type not in ("ticket", "resolution", "comment"):
        raise HTTPException(
            400,
            detail={
                "error": "invalid_type",
                "message": "attachment_type debe ser ticket, resolution o comment",
            },
        )

    if attachment_type == "comment" and not comment_id:
        raise HTTPException(
            400,
            detail={
                "error": "missing_comment_id",
                "message": "comment_id es requerido para adjuntos de comentario",
            },
        )

    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)
    att = _save_attachment_file(
        db=db,
        ticket=ticket,
        file=file,
        attachment_type=attachment_type,
        user_id=user_id,
        comment_id=comment_id,
    )

    logger.info(
        f"Adjunto {att.original_filename} ({attachment_type}) subido al ticket {ticket_id} "
        f"por usuario {user_id}"
    )
    return {"success": True, "data": att.to_dict()}


# ─────────────────────────────────────────────────────────────
# GET /tickets/{ticket_id}/attachments
# ─────────────────────────────────────────────────────────────

@router.get("/tickets/{ticket_id}/attachments")
def list_attachments(
    ticket_id: int,
    type: str | None = None,
    user: dict = require_perms("maint", ["maint.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.maint.services import ticket_service
    from itcj2.apps.maint.models.attachment import MaintAttachment

    user_id = int(user["sub"])
    ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)

    query = db.query(MaintAttachment).filter_by(ticket_id=ticket_id)
    if type and type in ("ticket", "resolution", "comment"):
        query = query.filter_by(attachment_type=type)

    attachments = query.order_by(MaintAttachment.uploaded_at.desc()).all()
    return {
        "success": True,
        "ticket_id": ticket_id,
        "total": len(attachments),
        "data": [att.to_dict() for att in attachments],
    }


# ─────────────────────────────────────────────────────────────
# GET /attachments/{attachment_id}/download
# ─────────────────────────────────────────────────────────────

@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    user: dict = require_perms("maint", ["maint.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.maint.services import ticket_service
    from itcj2.apps.maint.models.attachment import MaintAttachment

    user_id = int(user["sub"])
    att = db.get(MaintAttachment, attachment_id)
    if not att:
        raise HTTPException(
            404, detail={"error": "not_found", "message": "Archivo no encontrado"}
        )

    # Verificar visibilidad del ticket (lanza 403 si no tiene acceso)
    ticket_service.get_ticket_by_id(db, att.ticket_id, user_id=user_id)

    if att.is_purged:
        purged_str = (
            att.purged_at.strftime("%d/%m/%Y") if att.purged_at else "fecha desconocida"
        )
        raise HTTPException(
            410,
            detail={
                "error": "purged",
                "message": f"Este archivo fue eliminado el {purged_str}",
                "purged_at": att.purged_at.isoformat() if att.purged_at else None,
            },
        )

    if not att.filepath or not os.path.exists(att.filepath):
        raise HTTPException(
            404,
            detail={
                "error": "file_not_found",
                "message": "El archivo no existe en el servidor",
            },
        )

    ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "pdf": "application/pdf",
    }
    mime_type = att.mime_type or mime_map.get(ext, "application/octet-stream")

    return FileResponse(
        att.filepath,
        media_type=mime_type,
        filename=att.original_filename,
    )


# ─────────────────────────────────────────────────────────────
# DELETE /attachments/{attachment_id}
# ─────────────────────────────────────────────────────────────

@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    user: dict = require_perms("maint", ["maint.tickets.api.read.own"]),
    db: DbSession = None,
):
    """
    Eliminación manual por uploader o admin: borra fila + archivo físico.
    Diferente de la purga automática (que conserva la fila).
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.models.attachment import MaintAttachment

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "maint")
    is_admin = "admin" in user_roles

    att = db.get(MaintAttachment, attachment_id)
    if not att:
        raise HTTPException(
            404, detail={"error": "not_found", "message": "Archivo no encontrado"}
        )

    if not is_admin and att.uploaded_by_id != user_id:
        raise HTTPException(
            403,
            detail={
                "error": "forbidden",
                "message": "Solo el uploader o un admin pueden eliminar este archivo",
            },
        )

    if att.filepath and os.path.exists(att.filepath):
        try:
            os.remove(att.filepath)
        except OSError as exc:
            logger.warning(f"No se pudo eliminar el archivo físico {att.filepath}: {exc}")

    db.delete(att)
    db.commit()

    logger.info(f"Adjunto {attachment_id} eliminado manualmente por usuario {user_id}")
    return {"success": True, "message": "Archivo eliminado exitosamente"}
