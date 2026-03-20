"""
Páginas del área de jefe de departamento de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/department_head.py.

Rutas:
  GET /help-desk/department/              → Dashboard / tickets del departamento
  GET /help-desk/department/inventory     → Redirige a lista de inventario
  GET /help-desk/department/tickets/{id} → Detalle de ticket del departamento
  GET /help-desk/department/reports       → Reportes del departamento
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app, require_page_login
from itcj2.exceptions import PageForbidden

logger = logging.getLogger("itcj2.apps.helpdesk.pages.department")

router = APIRouter(prefix="/department", tags=["helpdesk-pages-department"])


def _require_department_head(user: dict) -> None:
    """Verifica que el usuario tenga el rol department_head en helpdesk."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        has_role = "department_head" in user_roles_in_app(_db, int(user["sub"]), "helpdesk")
    finally:
        _db.close()
    if not has_role:
        raise PageForbidden()


def _get_managed_department(user_id: int) -> dict:
    """Obtiene el departamento gestionado por el usuario o lanza 403."""
    from itcj2.core.services import positions_service
    from itcj2.database import SessionLocal

    with SessionLocal() as db:
        managed = positions_service.get_user_primary_managed_department(db, user_id)
    if not managed:
        raise HTTPException(status_code=403, detail="No tienes un departamento asignado como jefe")
    return managed


@router.get("", include_in_schema=False)
@router.get("/", name="helpdesk.pages.department.tickets")
async def tickets(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Vista de tickets del departamento gestionado por el jefe."""
    _require_department_head(user)
    user_id = int(user["sub"])
    managed = _get_managed_department(user_id)

    return render_helpdesk(request, "helpdesk/department_head/dashboard.html", {
        "title": f"Departamento - {managed['department']['name']}",
        "department": managed["department"],
        "position": managed["position"],
        "assignment": managed["assignment"],
        "active_page": "dashboard",
    })


@router.get("/inventory", name="helpdesk.pages.department.inventory")
async def inventory(
    request: Request,
    user: dict = Depends(require_page_app(
        "helpdesk", perms=["helpdesk.inventory.page.list.own_dept"]
    )),
):
    """Redirige a la lista de inventario del módulo de inventario."""
    return RedirectResponse("/help-desk/inventory/items", status_code=302)


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.department.ticket_detail")
async def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Vista de detalle de un ticket del departamento."""
    user_id = int(user["sub"])
    managed = _get_managed_department(user_id)

    can_consume_warehouse = False
    if user.get("role") == "admin":
        can_consume_warehouse = True
    else:
        from itcj2.apps.helpdesk.utils.warehouse_auth import get_warehouse_perms_via_helpdesk
        from itcj2.database import SessionLocal
        _wdb = SessionLocal()
        try:
            w_perms = get_warehouse_perms_via_helpdesk(_wdb, user_id)
            can_consume_warehouse = "warehouse.api.consume" in w_perms
        finally:
            _wdb.close()

    return render_helpdesk(request, "helpdesk/user/ticket_detail.html", {
        "title": f"Ticket #{ticket_id}",
        "ticket_id": ticket_id,
        "department": managed["department"],
        "position": managed["position"],
        "assignment": managed["assignment"],
        "active_page": "tickets",
        "can_consume_warehouse": can_consume_warehouse,
    })


@router.get("/reports", name="helpdesk.pages.department.reports")
async def reports(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.department"])),
):
    """Vista de reportes del departamento."""
    user_id = int(user["sub"])
    managed = _get_managed_department(user_id)

    return render_helpdesk(request, "helpdesk/department_head/reports.html", {
        "title": f"Reportes - {managed['department']['name']}",
        "department": managed["department"],
        "position": managed["position"],
        "assignment": managed["assignment"],
        "active_page": "reports",
    })
