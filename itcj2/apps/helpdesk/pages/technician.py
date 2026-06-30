"""
Páginas del área de técnicos de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/technician.py.

Rutas:
  GET /help-desk/technician/dashboard        → Dashboard personal del técnico (hace todo)
  GET /help-desk/technician/tickets/{id}     → Detalle de ticket (vista técnico)
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.technician")

router = APIRouter(prefix="/technician", tags=["helpdesk-pages-technician"])


def _helpdesk_roles(user_id: int) -> set:
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        return user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()


def _tech_team(user_roles: set):
    if "tech_desarrollo" in user_roles:
        return "desarrollo"
    if "tech_soporte" in user_roles:
        return "soporte"
    return None


def _query_tech_tickets(user_id: int, user_roles: set, tab: str, hist: str = "all", search: str = None) -> list:
    """Devuelve la lista de tickets para una pestaña del dashboard de técnico.

    Reemplaza los 4 ``loadX`` del JS por consultas server-side (mismo
    ``ticket_service.list_tickets`` que llamaba el endpoint API). ``resolved``
    aplica el filtro de fecha (hist) sobre ``resolved_at`` (prefijo de fecha).
    """
    from datetime import date, timedelta

    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        if tab == "assigned":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True, status=["ASSIGNED"], per_page=100)
            return res["tickets"]
        if tab == "inProgress":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True, status=["IN_PROGRESS"], per_page=100)
            return res["tickets"]
        if tab == "team":
            team = _tech_team(user_roles)
            if not team:
                return []
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_team=team, status=["ASSIGNED"],
                                              search=search or None, per_page=100)
            return res["tickets"]
        if tab == "resolved":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True,
                                              status=["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"],
                                              search=search or None, per_page=50)
            tickets = res["tickets"]
            today = date.today()
            cutoff = None
            if hist == "today":
                cutoff = today
            elif hist == "week":
                cutoff = today - timedelta(days=7)
            elif hist == "month":
                cutoff = today - timedelta(days=30)
            if cutoff is not None:
                cs = cutoff.isoformat()
                tickets = [t for t in tickets if (t.get("resolved_at") or "")[:10] >= cs]
            return tickets[:20]
        return []
    finally:
        _db.close()


_BADGE_MAP = {
    "assigned": ("queueBadge", "bg-warning"),
    "inProgress": ("workingBadge", "bg-info"),
    "team": ("teamBadge", "bg-secondary"),
}


@router.get("/dashboard", name="helpdesk.pages.technician.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.technician"])),
):
    """Dashboard personal del técnico.

    Una sola URL sirve dos representaciones (patrón canónico HTMX): petición HTMX
    no-boost con ``?tab=`` → solo el FRAGMENTO de esa lista; si no → la PÁGINA con
    las 4 listas renderizadas server-side.
    """
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    p = request.query_params

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        from itcj2.templates import render

        tab = p.get("tab", "assigned")
        hist = p.get("hist", "all")
        search = (p.get("search", "") or "").strip() or None
        tickets = _query_tech_tickets(user_id, user_roles, tab, hist, search)
        badge_id, badge_cls = _BADGE_MAP.get(tab, (None, None))
        return render(request, "helpdesk/technician/_dashboard_list.html", {
            "tickets": tickets,
            "tab": tab,
            "oob": bool(badge_id),
            "badge_id": badge_id,
            "badge_cls": badge_cls,
        })

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

    return render_helpdesk(request, "helpdesk/technician/dashboard.html", {
        "user_roles": user_roles,
        "active_page": "tech_dashboard",
        "can_consume_warehouse": can_consume_warehouse,
        "t_assigned": _query_tech_tickets(user_id, user_roles, "assigned"),
        "t_inprogress": _query_tech_tickets(user_id, user_roles, "inProgress"),
        "t_team": _query_tech_tickets(user_id, user_roles, "team"),
        "t_resolved": _query_tech_tickets(user_id, user_roles, "resolved", "week"),
    })


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.technician.ticket_detail")
async def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Vista detallada de un ticket para técnico."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    # Check if technician has warehouse consume permission
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
        "ticket_id": ticket_id,
        "user_roles": user_roles,
        "active_page": "tech_assignments",
        "can_consume_warehouse": can_consume_warehouse,
    })
