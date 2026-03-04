"""
Garments API v2 — 6 endpoints (gestión de prendas para voluntarios/admin).
Fuente: itcj/apps/vistetec/routes/api/garments.py
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["vistetec-garments"])
logger = logging.getLogger(__name__)


@router.get("")
def list_garments(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.garments.api.create"]),
    db: DbSession = None,
):
    """Lista todas las prendas (todos los estados) para voluntarios/admin."""
    from itcj2.apps.vistetec.services import garment_service

    per_page = min(per_page, 100)

    result = garment_service.list_all_garments(
        db,
        page=page,
        per_page=per_page,
        status=status,
        category=category,
        search=search,
    )
    return result


@router.post("", status_code=201)
async def create_garment(
    request: Request,
    user: dict = require_perms("vistetec", ["vistetec.garments.api.create"]),
    db: DbSession = None,
):
    """Registra una nueva prenda. Soporta FormData (con imagen) o JSON."""
    from itcj2.apps.vistetec.services import garment_service

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        data = {
            "name": form.get("name"),
            "description": form.get("description"),
            "category": form.get("category"),
            "gender": form.get("gender"),
            "size": form.get("size"),
            "brand": form.get("brand"),
            "color": form.get("color"),
            "material": form.get("material"),
            "condition": form.get("condition"),
            "donated_by_id": int(form["donated_by_id"]) if form.get("donated_by_id") else None,
        }
        image_file = form.get("image")
    else:
        data = await request.json()
        image_file = None

    if not data.get("name"):
        raise HTTPException(400, detail={"error": "missing_name", "message": "El nombre es obligatorio"})
    if not data.get("category"):
        raise HTTPException(400, detail={"error": "missing_category", "message": "La categoría es obligatoria"})
    if not data.get("condition"):
        raise HTTPException(400, detail={"error": "missing_condition", "message": "La condición es obligatoria"})

    try:
        user_id = int(user["sub"])
        garment = garment_service.create_garment(
            db,
            data=data,
            image_file=image_file,
            registered_by_id=user_id,
        )
        logger.info(f"Prenda '{garment.name}' creada por usuario {user_id}")
        return garment.to_dict()
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.put("/{garment_id}")
async def update_garment(
    garment_id: int,
    request: Request,
    user: dict = require_perms("vistetec", ["vistetec.garments.api.update"]),
    db: DbSession = None,
):
    """Actualiza una prenda. Soporta FormData (con imagen) o JSON."""
    from itcj2.apps.vistetec.services import garment_service

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        fields = ["name", "description", "category", "gender", "size", "brand", "color", "material", "condition"]
        data = {f: form[f] for f in fields if form.get(f) is not None}
        image_file = form.get("image")
    else:
        data = await request.json()
        image_file = None

    try:
        garment = garment_service.update_garment(db, garment_id, data, image_file)
        if not garment:
            raise HTTPException(404, detail={"error": "not_found", "message": "Prenda no encontrada"})
        logger.info(f"Prenda {garment_id} actualizada por usuario {int(user['sub'])}")
        return garment.to_dict()
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.delete("/{garment_id}")
def delete_garment(
    garment_id: int,
    user: dict = require_perms("vistetec", ["vistetec.garments.api.delete"]),
    db: DbSession = None,
):
    """Elimina una prenda (admin)."""
    from itcj2.apps.vistetec.services import garment_service

    if garment_service.delete_garment(db, garment_id):
        logger.info(f"Prenda {garment_id} eliminada por usuario {int(user['sub'])}")
        return {"message": "Prenda eliminada"}
    raise HTTPException(404, detail={"error": "not_found", "message": "Prenda no encontrada"})


@router.post("/{garment_id}/withdraw")
def withdraw_garment(
    garment_id: int,
    user: dict = require_perms("vistetec", ["vistetec.garments.api.withdraw"]),
    db: DbSession = None,
):
    """Retira una prenda del inventario."""
    from itcj2.apps.vistetec.services import garment_service

    garment = garment_service.withdraw_garment(db, garment_id)
    if not garment:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "Prenda no encontrada o no se puede retirar"},
        )
    logger.info(f"Prenda {garment_id} retirada por usuario {int(user['sub'])}")
    return garment.to_dict()


@router.get("/image/{image_path:path}")
def serve_garment_image(
    image_path: str,
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.list"]),
    db: DbSession = None,
):
    """Sirve la imagen de una prenda desde el directorio de uploads."""
    from itcj2.config import get_settings

    settings = get_settings()
    upload_path = getattr(settings, "VISTETEC_UPLOAD_PATH", None)

    if not upload_path:
        raise HTTPException(500, detail={"error": "config_error", "message": "Ruta de imágenes no configurada"})

    full_path = os.path.join(upload_path, image_path)

    if not os.path.exists(full_path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Imagen no encontrada"})

    return FileResponse(full_path)
