"""Páginas de administración de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/admin/categorias", name="maint_pages.admin.categories")
async def admin_categories(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.admin.page.categories"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/categories.html", {"active_page": "admin_categories"})


@router.get("/admin/areas", name="maint_pages.admin.areas")
async def admin_areas(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.admin.page.areas"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/areas.html", {"active_page": "admin_areas"})


@router.get("/admin/reportes", name="maint_pages.admin.reports")
async def admin_reports(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.admin.page.reports"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/reports.html", {"active_page": "admin_reports"})
