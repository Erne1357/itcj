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


@router.get("", include_in_schema=False)
@router.get("/", name="helpdesk.pages.secretary.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.secretary"])),
):
    """Dashboard de secretaría: KPIs del departamento, lista de tickets y opción de crear."""
    from itcj2.core.models.user import User

    user_id = int(user["sub"])
    db_user = User.query.get(user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    department = db_user.get_current_department()
    if not department:
        raise HTTPException(status_code=403, detail="Usuario sin departamento asignado")

    return render_helpdesk(request, "helpdesk/secretary/dashboard.html", {
        "title": "Secretaría - Dashboard",
        "department": department,
        "department_name": department.name,
    })
