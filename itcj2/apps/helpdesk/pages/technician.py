"""
Páginas del área de técnicos de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/technician.py.

Rutas:
  GET /help-desk/technician/dashboard        → Dashboard personal del técnico (hace todo)
  GET /help-desk/technician/tickets/{id}     → Detalle de ticket (vista técnico)
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import can_split, render_helpdesk
from itcj2.apps.helpdesk.utils.teams import tech_team
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.technician")

router = APIRouter(prefix="/technician", tags=["helpdesk-pages-technician"])


def _helpdesk_roles(user_id: int) -> set:
    # Del caché de authz (perf 2026-10-07): envuelve `user_roles_in_app`.
    from itcj2.core.services.authz_cache import cached_roles
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        return cached_roles(_db, user_id, "helpdesk")
    finally:
        _db.close()


def _tech_team(user_roles: set):
    """Equipo del técnico. El mapeo vive en `utils/teams.py` (única copia:
    lo comparten esta pestaña, el guard de la API y `nav.split_team()`)."""
    return tech_team(user_roles)


_TABS = ("assigned", "inProgress", "team", "resolved")


def _query_tech_tabs(user_id: int, user_roles: set, tabs, hist: str = "all",
                     search: str = None, db=None) -> dict:
    """Listas de las pestañas ``tabs`` del dashboard de técnico: ``{tab: [ticket]}``.

    Todas salen de UNA sola consulta (``ticket_service.list_ticket_sections``,
    mismos filtros que las ``list_tickets`` que reemplaza): antes la página
    completa hacía 4 listados, cada uno con su ``count`` y su juego de cargas de
    relaciones (36 y 46 sentencias en total medidas en dev con 7680/7681; ahora
    5, y las listas son 1). Cada ticket es el diccionario de
    ``Ticket.to_card_dict()``: lo que pinta la tarjeta, no el ``to_dict`` entero.

    ``resolved`` aplica el filtro de fecha (hist) sobre ``resolved_at`` (prefijo
    de fecha) DESPUÉS del límite de 50, como siempre: así el historial de una
    semana se arma de los 50 más recientes, no de todos los de esa semana.

    ``db``: sesión a reusar (la página completa arma las pestañas en UNA sesión:
    así lo que se recuerda por sesión, como la secretaría del Centro de Cómputo,
    se consulta una vez). Sin ella, abre y cierra la suya.
    """
    from datetime import date, timedelta

    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    secciones = {}
    if "assigned" in tabs:
        secciones["assigned"] = {"assigned_to_me": True, "status": ["ASSIGNED"], "limit": 100}
    if "inProgress" in tabs:
        secciones["inProgress"] = {"assigned_to_me": True, "status": ["IN_PROGRESS"], "limit": 100}
    if "team" in tabs:
        team = _tech_team(user_roles)
        if team:
            secciones["team"] = {"assigned_to_team": team, "status": ["ASSIGNED"],
                                 "search": search or None, "limit": 100}
    if "resolved" in tabs:
        secciones["resolved"] = {"assigned_to_me": True,
                                 "status": ["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"],
                                 "search": search or None, "limit": 50}

    listas = {}
    if secciones:
        own = db is None
        _db = SessionLocal() if own else db
        try:
            listas = ticket_service.list_ticket_sections(_db, user_id, user_roles, secciones)
        finally:
            if own:
                _db.close()

    out = {tab: listas.get(tab, []) for tab in tabs}
    if "resolved" in out:
        tickets = out["resolved"]
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
        out["resolved"] = tickets[:20]
    return out


def _query_tech_tickets(user_id: int, user_roles: set, tab: str, hist: str = "all",
                        search: str = None, db=None) -> list:
    """Lista de tickets de UNA pestaña (el fragmento HTMX que cada una recarga).
    Pestaña desconocida → ``[]``. Ver ``_query_tech_tabs``."""
    return _query_tech_tabs(user_id, user_roles, (tab,), hist, search, db)[tab]


_BADGE_MAP = {
    "assigned": ("queueBadge", "bg-warning"),
    "inProgress": ("workingBadge", "bg-info"),
    "team": ("teamBadge", "bg-secondary"),
}


@router.get("/dashboard", name="helpdesk.pages.technician.dashboard")
def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.technician"])),
):
    """Dashboard personal del técnico.

    Una sola URL sirve dos representaciones (patrón canónico HTMX): petición HTMX
    no-boost con ``?tab=`` → solo el FRAGMENTO de esa lista; si no → la PÁGINA con
    las 4 listas renderizadas server-side.

    ``can_split`` va a los DOS caminos (mismo criterio que
    ``admin.assign_tickets``): el fragmento es lo que cada pestaña recarga por
    HTMX, así que si solo llegara a la página el botón "Partir" desaparecería
    al cambiar de pestaña.
    """
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    p = request.query_params
    split_scope = can_split(user)

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
            "can_split": split_scope,
        })

    from itcj2.database import SessionLocal

    # UNA sesión para el permiso de almacén y las 4 pestañas (perf 2026-10-07).
    _db = SessionLocal()
    try:
        can_consume_warehouse = False
        if user.get("role") == "admin":
            can_consume_warehouse = True
        else:
            from itcj2.apps.helpdesk.utils.warehouse_auth import get_warehouse_perms_via_helpdesk
            w_perms = get_warehouse_perms_via_helpdesk(_db, user_id)
            can_consume_warehouse = "warehouse.api.consume" in w_perms

        tabs = _query_tech_tabs(user_id, user_roles, _TABS, hist="week", db=_db)
        listas = {
            "t_assigned": tabs["assigned"],
            "t_inprogress": tabs["inProgress"],
            "t_team": tabs["team"],
            "t_resolved": tabs["resolved"],
        }
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/technician/dashboard.html", {
        "user_roles": user_roles,
        "active_page": "tech_dashboard",
        "can_consume_warehouse": can_consume_warehouse,
        "can_split": split_scope,
        **listas,
    })


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.technician.ticket_detail")
def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Vista detallada de un ticket para técnico."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    # "Partir ticket" (fase 2, tarea 11): mismo criterio que el dashboard
    # (tarea 10) — helpers compartidos en pages/nav.py. Aquí, a diferencia de
    # las listas, hace falta también el EQUIPO: el detalle no acota nada, así
    # que el cliente reproduce D17 (lo propio o la cola de MI equipo).
    split_scope = can_split(user)
    actor_team = tech_team(user_roles)

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
        "split_scope": split_scope,
        "split_team": actor_team,
    })
