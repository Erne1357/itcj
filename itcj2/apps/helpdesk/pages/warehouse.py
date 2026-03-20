"""
Páginas del Almacén (Warehouse) integradas en Help-Desk.

Rutas:
  GET /help-desk/warehouse/dashboard   → Dashboard del almacén
  GET /help-desk/warehouse/products    → Catálogo de productos
  GET /help-desk/warehouse/categories  → Categorías y subcategorías
  GET /help-desk/warehouse/entries     → Entradas de stock (FIFO)
  GET /help-desk/warehouse/movements   → Historial de movimientos
  GET /help-desk/warehouse/reports     → Reportes del almacén
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.apps.helpdesk.utils.warehouse_auth import require_warehouse_page

logger = logging.getLogger("itcj2.apps.helpdesk.pages.warehouse")

router = APIRouter(prefix="/warehouse", tags=["helpdesk-pages-warehouse"])


@router.get("/dashboard", name="helpdesk.pages.warehouse.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.dashboard")),
):
    """Dashboard del almacén: métricas globales y productos bajo punto de restock."""
    return render_helpdesk(request, "helpdesk/warehouse/dashboard.html", {
        "active_page": "warehouse_dashboard",
    })


@router.get("/products", name="helpdesk.pages.warehouse.products")
async def products(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.products")),
):
    """Catálogo de productos del almacén con stock actual."""
    return render_helpdesk(request, "helpdesk/warehouse/products.html", {
        "active_page": "warehouse_products",
    })


@router.get("/categories", name="helpdesk.pages.warehouse.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.categories")),
):
    """Gestión de categorías y subcategorías del almacén."""
    return render_helpdesk(request, "helpdesk/warehouse/categories.html", {
        "active_page": "warehouse_categories",
    })


@router.get("/entries", name="helpdesk.pages.warehouse.entries")
async def entries(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.entries")),
):
    """Registro de entradas de stock (lotes FIFO)."""
    return render_helpdesk(request, "helpdesk/warehouse/entries.html", {
        "active_page": "warehouse_entries",
    })


@router.get("/movements", name="helpdesk.pages.warehouse.movements")
async def movements(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.movements")),
):
    """Historial completo de movimientos del almacén."""
    return render_helpdesk(request, "helpdesk/warehouse/movements.html", {
        "active_page": "warehouse_movements",
    })


@router.get("/reports", name="helpdesk.pages.warehouse.reports")
async def reports(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.reports")),
):
    """Reportes del almacén: consumo, movimientos y valoración de inventario."""
    return render_helpdesk(request, "helpdesk/warehouse/reports.html", {
        "active_page": "warehouse_reports",
    })
