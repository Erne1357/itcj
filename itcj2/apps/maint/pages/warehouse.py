"""Páginas del Almacén integradas en Mantenimiento.

Las páginas viven en el árbol de rutas de maint pero consumen el almacén global
(`/api/warehouse/v2/*`). Auth cross-app vía `require_warehouse_page`: los perms
warehouse se derivan del rol maint del usuario (`core_role_permissions`),
sin requerir UserAppRole explícita en la app warehouse para la página.

Rutas:
  GET /maint/warehouse/dashboard   → Dashboard del almacén
  GET /maint/warehouse/products    → Catálogo de productos
  GET /maint/warehouse/categories  → Categorías y subcategorías
  GET /maint/warehouse/entries     → Entradas de stock (FIFO)
  GET /maint/warehouse/movements   → Historial de movimientos
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.apps.maint.pages.nav import render_maint
from itcj2.apps.maint.utils.warehouse_auth import require_warehouse_page

router = APIRouter(tags=["maint-pages-warehouse"])


@router.get("/warehouse/dashboard", name="maint_pages.warehouse.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.dashboard")),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/dashboard.html", {"active_page": "warehouse_dashboard"})


@router.get("/warehouse/categories", name="maint_pages.warehouse.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.categories")),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/categories.html", {"active_page": "warehouse_categories"})


@router.get("/warehouse/products", name="maint_pages.warehouse.products")
async def products(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.products")),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/products.html", {"active_page": "warehouse_products"})


@router.get("/warehouse/entries", name="maint_pages.warehouse.entries")
async def entries(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.entries")),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/entries.html", {"active_page": "warehouse_entries"})


@router.get("/warehouse/movements", name="maint_pages.warehouse.movements")
async def movements(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.movements")),
) -> HTMLResponse:
    return render_maint(request, "maint/warehouse/movements.html", {"active_page": "warehouse_movements"})
