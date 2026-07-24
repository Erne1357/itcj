"""
Páginas del área de usuario final de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/user.py.

Rutas:
  GET /help-desk/user/create           → Crear ticket
  GET /help-desk/user/my-tickets       → Mis tickets
  GET /help-desk/user/tickets/{id}     → Detalle de ticket
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.user")

router = APIRouter(prefix="/user", tags=["helpdesk-pages-user"])

MAX_UNRATED_TICKETS = 3

# Dependencia: usuario autenticado con acceso a helpdesk
_require_helpdesk = require_page_app("helpdesk")


def _query_my_tickets_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta los tickets del usuario (created_by_me) para "Mis Tickets".

    Reusado por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento). Reusa
    ``ticket_service.list_tickets`` (mismo motor que el endpoint API). Devuelve la
    selección actual de filtros para prefijar el form en el render completo.
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    p = request.query_params
    raw_status = p.get("status", "")
    if raw_status == "PENDING_RATING":
        # Pseudo-filtro "Por Calificar" → tickets resueltos (con/ sin éxito).
        status = ["RESOLVED_SUCCESS", "RESOLVED_FAILED"]
    elif raw_status:
        status = [s.strip().upper() for s in raw_status.split(",") if s.strip()] or None
    else:
        status = None

    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1

    area = p.get("area") or None
    search = (p.get("search", "") or "").strip() or None

    _db = SessionLocal()
    try:
        result = ticket_service.list_tickets(
            _db,
            user_id=user_id,
            user_roles=user_roles,
            created_by_me=True,
            status=status,
            area=area,
            search=search,
            page=page,
            per_page=10,
        )
    finally:
        _db.close()

    return {
        "tickets": result["tickets"],
        "total": result["total"],
        "current_page": result["current_page"],
        "total_pages": result["pages"],
        "f_status": raw_status,
        "f_area": p.get("area", ""),
        "f_search": p.get("search", ""),
        "has_filters": bool(raw_status or area or search),
    }


@router.get("/create", name="helpdesk.pages.user.create_ticket")
async def create_ticket(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.create"])),
):
    """Página para crear un nuevo ticket."""
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.core.models.position import UserPosition
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        from itcj2.apps.helpdesk.models.area import Area

        user_roles = user_roles_in_app(_db, user_id, "helpdesk")

        unrated_count = _db.query(Ticket).filter(
            Ticket.requester_id == user_id,
            Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED"]),
            Ticket.rating_attention.is_(None),
        ).count()

        can_create_for_other = "admin" in user_roles
        if not can_create_for_other:
            user_positions = _db.query(UserPosition).filter_by(user_id=user_id, is_active=True).all()
            for up in user_positions:
                if up.position and up.position.department:
                    if up.position.department.code == "comp_center":
                        can_create_for_other = True
                        break

        areas = (
            _db.query(Area)
            .filter_by(is_active=True)
            .order_by(Area.display_order)
            .all()
        )
        areas_data = [a.to_dict() for a in areas]
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/user/create_ticket.html", {
        "title": "Crear Ticket",
        "user_roles": user_roles,
        "can_create_for_other": can_create_for_other,
        "unrated_count": unrated_count,
        "max_unrated": MAX_UNRATED_TICKETS,
        "active_page": "create_ticket",
        "areas": areas_data,
    })


@router.get("/my-tickets", name="helpdesk.pages.user.my_tickets")
async def my_tickets(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Lista de tickets del usuario autenticado.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa.
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-tickets-results) + contador OOB.
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        user_roles = user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()

    ctx = _query_my_tickets_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/user/_my_tickets_results.html", ctx)

    ctx.update({
        "title": "Mis Tickets",
        "user_roles": user_roles,
        "active_page": "my_tickets",
    })
    return render_helpdesk(request, "helpdesk/user/my_tickets.html", ctx)


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.user.ticket_detail")
async def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app(
        "helpdesk",
        perms=["helpdesk.tickets.api.read.own", "helpdesk.tickets.api.read.all", "helpdesk.tickets.api.read.subtree"],
    )),
):
    """Vista de detalle de un ticket específico."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        user_roles = user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()

    can_consume_warehouse = False
    if user.get("role") == "admin":
        can_consume_warehouse = True
    else:
        from itcj2.apps.helpdesk.utils.warehouse_auth import get_warehouse_perms_via_helpdesk
        from itcj2.database import SessionLocal as _SL
        _wdb = _SL()
        try:
            w_perms = get_warehouse_perms_via_helpdesk(_wdb, user_id)
            can_consume_warehouse = "warehouse.api.consume" in w_perms
        finally:
            _wdb.close()

    return render_helpdesk(request, "helpdesk/user/ticket_detail.html", {
        "title": f"Ticket #{ticket_id}",
        "ticket_id": ticket_id,
        "user_id": user_id,
        "user_roles": user_roles,
        "active_page": "my_tickets",
        "can_consume_warehouse": can_consume_warehouse,
    })
