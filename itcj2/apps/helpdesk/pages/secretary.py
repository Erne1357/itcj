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


def _helpdesk_departments(db, user_id: int) -> list:
    """Los departamentos que CUENTAN para helpdesk: por procedencia, con respaldo.

    Antes esto era `db_user.get_current_department()`, el resolver AGNÓSTICO:
    devuelve cualquier departamento con puesto vigente y desempata por el MÁS
    ANTIGUO, sin mirar si ese puesto otorga la app. Caso real: auxiliar en
    Ingeniería Industrial (alta de junio, no otorga helpdesk) + secretaria en
    División de Estudios Profesionales (alta de septiembre, sí lo otorga). El
    dashboard salía titulado «Ingeniería Industrial», que es justo el
    departamento que NO le da acceso.

    Y es PLURAL a propósito: una secretaria puede serlo de dos departamentos, y
    en singular veía uno solo. Es el mismo resolver que usa `list_tickets` para
    decidir qué puede ver, así que el título de la página y su contenido ya no
    pueden discrepar.
    """
    from itcj2.core.services.departments_service import app_departments
    return [d for d in app_departments(db, user_id, "helpdesk") if d.is_active]


def _query_dept_tickets_ctx(request: Request, user_id: int, user_roles: set,
                            department_ids: set) -> dict:
    """Lista los tickets del departamento para el dashboard de secretaría.

    Reusado por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento). Reusa
    ``ticket_service.list_tickets`` con el conjunto EXPLÍCITO de departamentos y
    los roles reales del usuario.

    El conjunto de departamentos lo calcula `ticket_service.department_scope_ids`,
    el MISMO que usa la visibilidad. Antes esta página se lo inventaba: el subárbol
    del departamento agnóstico. A una secretaría le sobraba anchura (filtraba por
    un subárbol que la visibilidad no le abría) y a quien tuviera
    `read.subtree` un conjunto exacto le habría borrado sus sub-departamentos.

    `department_ids=None` (y no un conjunto vacío) cuando no hay scope: un
    conjunto vacío se traduce en `IN (-1)` y deja la página EN BLANCO, incluidos
    sus propios tickets. Hoy no le pasa a nadie —quien abre esta página siempre
    trae `read.department`—, pero eso es un acoplamiento entre dos permisos que
    se rompe al primer cambio de DML, y el modo de fallo debe ser degradar, no
    apagarse.
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
            department_ids=department_ids,
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
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        departments = _helpdesk_departments(_db, user_id)
        if not departments:
            raise HTTPException(status_code=403, detail="Usuario sin departamento asignado")

        # No `{d.id for d in departments}`: quien tenga `read.subtree` alcanza
        # además sus sub-departamentos, y un conjunto exacto se los quitaría.
        from itcj2.apps.helpdesk.services.ticket_service import department_scope_ids
        department_ids = department_scope_ids(_db, user_id) or None
        # El primero es el desempate canónico de `app_departments`; da título a la
        # página cuando hay varios.
        department = departments[0]
        department_name = " · ".join(d.name for d in departments)
        user_roles = user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()

    ctx = _query_dept_tickets_ctx(request, user_id, user_roles, department_ids)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/secretary/_dashboard_tickets_results.html", ctx)

    ctx.update({
        "title": "Secretaría - Dashboard",
        "department": department,
        "department_name": department_name,
    })
    return render_helpdesk(request, "helpdesk/secretary/dashboard.html", ctx)
