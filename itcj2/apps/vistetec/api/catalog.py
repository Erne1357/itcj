"""
Catalog API v2 — 5 endpoints.
Fuente: itcj/apps/vistetec/routes/api/catalog.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["vistetec-catalog"])
logger = logging.getLogger(__name__)


@router.get("")
def list_catalog(
    page: int = 1,
    per_page: int = 12,
    category: Optional[str] = None,
    gender: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    condition: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.list"]),
    db: DbSession = None,
):
    """Lista prendas disponibles con filtros y paginación."""
    from itcj2.apps.vistetec.services import catalog_service

    per_page = min(per_page, 50)

    result = catalog_service.list_garments(
        db,
        page=page,
        per_page=per_page,
        category=category,
        gender=gender,
        size=size,
        color=color,
        condition=condition,
        search=search,
    )
    return result


@router.get("/categories")
def list_categories(
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.categories"]),
    db: DbSession = None,
):
    """Categorías con prendas disponibles."""
    from itcj2.apps.vistetec.services import catalog_service

    return catalog_service.get_available_categories(db)


@router.get("/sizes")
def list_sizes(
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.categories"]),
    db: DbSession = None,
):
    """Tallas con prendas disponibles."""
    from itcj2.apps.vistetec.services import catalog_service

    return catalog_service.get_available_sizes(db)


@router.get("/stats")
def get_catalog_stats(
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.stats"]),
    db: DbSession = None,
):
    """Estadísticas generales del catálogo."""
    from itcj2.apps.vistetec.services import catalog_service

    return catalog_service.get_catalog_stats(db)


@router.get("/{garment_id}")
def get_garment_detail(
    garment_id: int,
    user: dict = require_perms("vistetec", ["vistetec.catalog.api.detail"]),
    db: DbSession = None,
):
    """Detalle de una prenda del catálogo."""
    from itcj2.apps.vistetec.services import catalog_service

    detail = catalog_service.get_garment_detail(db, garment_id)
    if not detail:
        raise HTTPException(404, detail={"error": "not_found", "message": "Prenda no encontrada"})
    return detail
