"""Página de bienvenida de la app de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/", name="maint_pages.home")
async def home_landing(
    request: Request,
    user: dict = Depends(require_page_app("maint")),
) -> HTMLResponse:
    """Página de bienvenida — muestra CTA según rol del usuario."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    roles = set()
    _db = SessionLocal()
    try:
        roles = set(user_roles_in_app(_db, user_id, "maint"))
    finally:
        _db.close()

    # Determinar el CTA principal según rol
    if roles & {"admin", "dispatcher"}:
        cta_label = "Abrir Panel"
        cta_url = "/maintenance/tickets"
        cta_icon = "fa-tachometer-alt"
        welcome_msg = "Gestiona y coordina las solicitudes del departamento."
    elif "tech_maint" in roles:
        cta_label = "Ver Mis Asignaciones"
        cta_url = "/maintenance/tickets"
        cta_icon = "fa-tools"
        welcome_msg = "Consulta los tickets asignados a ti."
    elif roles & {"department_head", "secretary"}:
        cta_label = "Solicitudes del Departamento"
        cta_url = "/maintenance/tickets"
        cta_icon = "fa-clipboard-list"
        welcome_msg = "Revisa el estado de las solicitudes de tu departamento."
    else:
        cta_label = "Crear Solicitud"
        cta_url = "/maintenance/tickets/create"
        cta_icon = "fa-plus-circle"
        welcome_msg = "Reporta un problema o solicita un servicio de mantenimiento."

    return render_maint(request, "maint/home_landing.html", {
        "cta_label": cta_label,
        "cta_url": cta_url,
        "cta_icon": cta_icon,
        "welcome_msg": welcome_msg,
        "user_roles": roles,
    })
