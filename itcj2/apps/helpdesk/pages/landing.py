"""
Landing page y redirección por rol de Help-Desk.
Equivalente a las rutas raíz del blueprint helpdesk_pages_bp en Flask.

Rutas:
  GET  /help-desk/   → Landing page (home_landing.html)
  POST /help-desk/   → Redirige al dashboard por rol (respuesta JSON)
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_login

logger = logging.getLogger("itcj2.apps.helpdesk.pages.landing")

router = APIRouter(tags=["helpdesk-pages-landing"])

# Mapa de rol → URL de destino (equivalente a role_home() y redirect_by_role() de Flask)
_ROLE_REDIRECT: dict[str, str] = {
    "admin": "/help-desk/admin/home",
    "secretary": "/help-desk/user/create",
    "tech_desarrollo": "/help-desk/technician/dashboard",
    "tech_soporte": "/help-desk/technician/dashboard",
    "department_head": "/help-desk/department/",
    "staff": "/help-desk/user/create",
}

# Orden de prioridad para seleccionar destino cuando el usuario tiene varios roles
_ROLE_PRIORITY = ["admin", "tech_desarrollo", "tech_soporte", "department_head", "secretary", "staff"]


@router.get("/", name="helpdesk.pages.landing.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Landing page de Help-Desk — punto de entrada para todos los usuarios."""
    return render_helpdesk(request, "helpdesk/home_landing.html", {"title": "Help-Desk"})


@router.post("/", name="helpdesk.pages.landing.redirect_by_role")
async def redirect_by_role(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Retorna JSON con la URL de redirección según el rol del usuario.

    El botón "Pedir Ayuda" del landing hace POST aquí y redirige al
    dashboard correspondiente según la prioridad de roles.
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    _db = SessionLocal()
    try:
        user_roles = set(user_roles_in_app(_db, user_id, "helpdesk"))
    finally:
        _db.close()

    for role in _ROLE_PRIORITY:
        if role in user_roles:
            return JSONResponse({"redirect": _ROLE_REDIRECT[role]})

    logger.error("Usuario %s no tiene roles asignados en Help-Desk. Roles: %s", user_id, user_roles)
    return JSONResponse({"error": "no_roles"}, status_code=403)
