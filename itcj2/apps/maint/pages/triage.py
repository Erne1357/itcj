"""Página del tablero de triage/enrutado de tickets de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/triage", name="maint_pages.triage.board")
async def triage_board(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.assignments.page.triage"])),
) -> HTMLResponse:
    from itcj2.database import get_db as _get_db
    from itcj2.core.services.authz_service import user_roles_in_app

    user_roles = []
    try:
        db = next(_get_db())
        uid = int(user["sub"])
        user_roles = list(user_roles_in_app(db, uid, "maint"))
    except Exception:
        pass

    # El coordinador general necesita ver su propia cola además de los sin enrutar
    is_general_coordinator = "maint_general_coordinator" in user_roles
    is_admin = user.get("role") == "admin" or "admin" in user_roles

    return render_maint(request, "maint/triage/board.html", {
        "active_page": "triage",
        "is_general_coordinator": is_general_coordinator,
        "is_admin": is_admin,
    })
