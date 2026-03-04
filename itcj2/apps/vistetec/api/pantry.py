"""
Pantry API v2 — 13 endpoints (items, stock y campañas).
Fuente: itcj/apps/vistetec/routes/api/pantry.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.vistetec.schemas.pantry import (
    PantryItemBody,
    StockMovementBody,
    PantryCampaignBody,
)

router = APIRouter(tags=["vistetec-pantry"])
logger = logging.getLogger(__name__)


# ── Items ─────────────────────────────────────────────────────────────────────

@router.get("/items")
def list_items(
    page: int = 1,
    per_page: int = 20,
    category: Optional[str] = None,
    search: Optional[str] = None,
    is_active: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Lista items de despensa con filtros."""
    from itcj2.apps.vistetec.services import pantry_service

    active_filter = None
    if is_active is not None:
        active_filter = is_active.lower() == "true"

    return pantry_service.get_items(
        db,
        category=category,
        search=search,
        is_active=active_filter,
        page=page,
        per_page=per_page,
    )


@router.post("/items", status_code=201)
def create_item(
    body: PantryItemBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage"]),
    db: DbSession = None,
):
    """Crea un item de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        item = pantry_service.create_item(db, body.model_dump())
        logger.info(f"Item de despensa '{item.name}' creado por usuario {int(user['sub'])}")
        return {"message": "Artículo creado", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.get("/items/{item_id}")
def get_item(
    item_id: int,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Obtiene un item de despensa por ID."""
    from itcj2.apps.vistetec.services import pantry_service

    item = pantry_service.get_item_by_id(db, item_id)
    if not item:
        raise HTTPException(404, detail={"error": "not_found", "message": "Artículo no encontrado"})
    return item.to_dict()


@router.put("/items/{item_id}")
def update_item(
    item_id: int,
    body: PantryItemBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage"]),
    db: DbSession = None,
):
    """Actualiza un item de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        item = pantry_service.update_item(db, item_id, body.model_dump(exclude_none=True))
        logger.info(f"Item de despensa {item_id} actualizado por usuario {int(user['sub'])}")
        return {"message": "Artículo actualizado", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.delete("/items/{item_id}")
def delete_item(
    item_id: int,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage"]),
    db: DbSession = None,
):
    """Desactiva un item de despensa (soft delete)."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        pantry_service.deactivate_item(db, item_id)
        logger.info(f"Item de despensa {item_id} desactivado por usuario {int(user['sub'])}")
        return {"message": "Artículo desactivado"}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.get("/categories")
def list_pantry_categories(
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Lista categorías de items de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    return pantry_service.get_categories(db)


# ── Stock ─────────────────────────────────────────────────────────────────────

@router.get("/stock")
def get_stock_summary(
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Resumen del inventario actual."""
    from itcj2.apps.vistetec.services import pantry_service

    return pantry_service.get_stock_summary(db)


@router.post("/stock/in")
def stock_in(
    body: StockMovementBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage"]),
    db: DbSession = None,
):
    """Registra entrada de stock."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        item = pantry_service.stock_in(
            db,
            item_id=body.item_id,
            quantity=body.quantity,
            notes=body.notes,
        )
        logger.info(f"Entrada de stock registrada por usuario {int(user['sub'])}")
        return {"message": "Entrada registrada", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/stock/out")
def stock_out(
    body: StockMovementBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage"]),
    db: DbSession = None,
):
    """Registra salida de stock."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        item = pantry_service.stock_out(
            db,
            item_id=body.item_id,
            quantity=body.quantity,
            notes=body.notes,
        )
        logger.info(f"Salida de stock registrada por usuario {int(user['sub'])}")
        return {"message": "Salida registrada", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


# ── Campañas ──────────────────────────────────────────────────────────────────

@router.get("/campaigns")
def list_campaigns(
    page: int = 1,
    per_page: int = 20,
    is_active: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Lista campañas de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    active_filter = None
    if is_active is not None:
        active_filter = is_active.lower() == "true"

    return pantry_service.get_campaigns(
        db,
        is_active=active_filter,
        page=page,
        per_page=per_page,
    )


@router.get("/campaigns/active")
def list_active_campaigns(
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Lista campañas activas."""
    from itcj2.apps.vistetec.services import pantry_service

    return pantry_service.get_active_campaigns(db)


@router.post("/campaigns", status_code=201)
def create_campaign(
    body: PantryCampaignBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage_campaigns"]),
    db: DbSession = None,
):
    """Crea una campaña de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        campaign = pantry_service.create_campaign(db, body.model_dump(exclude_none=True))
        logger.info(f"Campaña '{campaign.name}' creada por usuario {int(user['sub'])}")
        return {"message": "Campaña creada", "campaign": campaign.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: int,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.view"]),
    db: DbSession = None,
):
    """Obtiene una campaña por ID."""
    from itcj2.apps.vistetec.services import pantry_service

    campaign = pantry_service.get_campaign_by_id(db, campaign_id)
    if not campaign:
        raise HTTPException(404, detail={"error": "not_found", "message": "Campaña no encontrada"})
    return campaign.to_dict()


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: int,
    body: PantryCampaignBody,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage_campaigns"]),
    db: DbSession = None,
):
    """Actualiza una campaña de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        campaign = pantry_service.update_campaign(db, campaign_id, body.model_dump(exclude_none=True))
        logger.info(f"Campaña {campaign_id} actualizada por usuario {int(user['sub'])}")
        return {"message": "Campaña actualizada", "campaign": campaign.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    user: dict = require_perms("vistetec", ["vistetec.pantry.api.manage_campaigns"]),
    db: DbSession = None,
):
    """Desactiva una campaña de despensa."""
    from itcj2.apps.vistetec.services import pantry_service

    try:
        pantry_service.deactivate_campaign(db, campaign_id)
        logger.info(f"Campaña {campaign_id} desactivada por usuario {int(user['sub'])}")
        return {"message": "Campaña desactivada"}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})
