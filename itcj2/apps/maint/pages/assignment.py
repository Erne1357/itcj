"""Página del tablero de asignación de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/asignacion", name="maint_pages.assignment.board")
async def assignment_board(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.assignments.page.list"])),
) -> HTMLResponse:
    return render_maint(request, "maint/assignment/board.html", {
        "active_page": "assignment",
    })
