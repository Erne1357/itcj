"""
Páginas del dashboard de secretaría de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/secretary.py.

Rutas:
  GET /help-desk/secretary/  → Dashboard de secretaría
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.secretary")

router = APIRouter(prefix="/secretary", tags=["helpdesk-pages-secretary"])


def _query_dept_tickets_ctx(request: Request, user_id: int, user_roles: set, department_id: int) -> dict:
    """Lista los tickets del departamento para el dashboard de secretaría.

    Reusado por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento). Reusa
    ``ticket_service.list_tickets`` con el ``department_id`` y los roles reales del
    usuario (mismo scoping que el endpoint API que llamaba el JS anterior).
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    p = request.query_params
    status = p.get("status") or None
    area = p.get("area") or None
    search = (p.get("search", "") or "").strip() or None
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1

    _db = SessionLocal()
    try:
        result = ticket_service.list_tickets(
            _db,
            user_id=user_id,
            user_roles=user_roles,
            department_id=department_id,
            status=[status] if status else None,
            area=area,
            search=search,
            page=page,
            per_page=20,
        )
    finally:
        _db.close()

    return {
        "tickets": result["tickets"],
        "total": result["total"],
        "current_page": result["current_page"],
        "total_pages": result["pages"],
        "f_status": p.get("status", ""),
        "f_area": p.get("area", ""),
        "f_search": p.get("search", ""),
        "has_filters": bool(status or area or search),
    }


@router.get("", include_in_schema=False)
@router.get("/", name="helpdesk.pages.secretary.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.secretary"])),
):
    """Dashboard de secretaría: KPIs del departamento, lista de tickets y opción de crear.

    Una sola URL sirve dos representaciones (patrón canónico HTMX): petición HTMX
    no-boost (filtros/paginación de la lista) → solo el FRAGMENTO; si no → la PÁGINA.
    """
    from itcj2.core.models.user import User
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        db_user = _db.get(User, user_id)
        if not db_user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        department = db_user.get_current_department()
        if not department:
            raise HTTPException(status_code=403, detail="Usuario sin departamento asignado")

        department_id = department.id
        user_roles = user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()

    ctx = _query_dept_tickets_ctx(request, user_id, user_roles, department_id)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/secretary/_dashboard_tickets_results.html", ctx)

    ctx.update({
        "title": "Secretaría - Dashboard",
        "department": department,
        "department_name": department.name,
    })
    return render_helpdesk(request, "helpdesk/secretary/dashboard.html", ctx)
