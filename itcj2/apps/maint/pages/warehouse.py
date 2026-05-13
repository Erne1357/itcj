"""Páginas del Almacén de Mantenimiento.

Cada página requiere un permiso granular `maint.warehouse.page.{seccion}`
(ver `database/DML/maint/07_warehouse_pages_granular.sql`).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages-warehouse"])


@router.get("/warehouse/dashboard", name="maint_pages.warehouse.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.warehouse.page.dashboard"])),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/dashboard.html", {"active_page": "warehouse_dashboard"})


@router.get("/warehouse/categories", name="maint_pages.warehouse.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.warehouse.page.categories"])),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/categories.html", {"active_page": "warehouse_categories"})


@router.get("/warehouse/products", name="maint_pages.warehouse.products")
async def products(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.warehouse.page.products"])),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/products.html", {"active_page": "warehouse_products"})


@router.get("/warehouse/entries", name="maint_pages.warehouse.entries")
async def entries(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.warehouse.page.entries"])),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/entries.html", {"active_page": "warehouse_entries"})


@router.get("/warehouse/movements", name="maint_pages.warehouse.movements")
async def movements(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.warehouse.page.movements"])),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/movements.html", {"active_page": "warehouse_movements"})
