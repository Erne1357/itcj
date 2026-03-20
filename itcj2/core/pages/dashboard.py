"""
Página de dashboard del Core (equivalente a itcj/core/routes/pages/dashboard.py).

Rutas:
  GET /itcj/dashboard  → Dashboard principal para personal no-estudiante
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from itcj2.dependencies import get_db, require_page_login
from itcj2.templates import render

router = APIRouter(tags=["core-pages"])

# Roles que tienen acceso al dashboard de escritorio.
# Estudiantes y usuarios sin ninguno de estos roles van al móvil.
_DESKTOP_ROLES = frozenset({"coordinator", "social_service", "admin", "staff"})


@router.get("/dashboard", name="core.pages.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_login),
    db: Session = Depends(get_db),
):
    """Dashboard principal del sistema.

    Redirige a la vista móvil si el user-agent es móvil y el usuario no
    forzó la vista desktop (cookie ``prefer_desktop``).
    También redirige al móvil si el usuario no tiene roles de escritorio
    (ej. solo tiene rol de estudiante).
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.core.services.mobile_service import is_mobile_user_agent

    prefer_desktop = request.cookies.get("prefer_desktop")
    ua = request.headers.get("user-agent", "")

    if not prefer_desktop and is_mobile_user_agent(ua):
        return RedirectResponse("/itcj/m/", status_code=302)

    uid = int(user["sub"])
    user_roles = set(user_roles_in_app(db, uid, "itcj"))

    if not user_roles & _DESKTOP_ROLES:
        return RedirectResponse("/itcj/m/", status_code=302)

    return render(request, "core/dashboard/dashboard.html")
