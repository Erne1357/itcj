"""Páginas de administración de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/admin/categories", name="maint_pages.admin.categories")
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


@router.get("/admin/reports", name="maint_pages.admin.reports")
async def admin_reports(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.admin.page.reports"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/reports.html", {"active_page": "admin_reports"})


@router.get("/admin/stats", name="maint_pages.admin.stats")
async def admin_stats(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.stats.page.list"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/stats.html", {"active_page": "admin_stats"})


@router.get("/admin/analysis", name="maint_pages.admin.analysis")
async def admin_analysis(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.analysis.page.list"])),
) -> HTMLResponse:
    return render_maint(request, "maint/admin/analysis.html", {"active_page": "admin_analysis"})


@router.get("/admin/dashboard", name="maint_pages.admin.dashboard")
async def admin_dashboard(
    request: Request,
    user: dict = Depends(require_page_app(
        "maint",
        perms=["maint.dashboard.page.full", "maint.dashboard.page.summary"],
    )),
) -> HTMLResponse:
    """Dashboard departamental. Sirve la misma página para `full` y `summary`;
    el JS detecta vía API qué nivel mostrar (full gana si user tiene ambos)."""
    return render_maint(request, "maint/admin/dashboard.html", {"active_page": "admin_dashboard"})
