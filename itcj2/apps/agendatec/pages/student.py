"""
Páginas de estudiantes para AgendaTec.
Equivalente a itcj/apps/agendatec/routes/pages/student.py.

Rutas:
  GET /agendatec/student/home     → Home del estudiante
  GET /agendatec/student/requests → Mis solicitudes
  GET /agendatec/student/request  → Nueva solicitud
  GET /agendatec/student/close    → Ventana cerrada

La lógica de gate_student_period (before_request en Flask) se implementa
directamente en cada handler para evitar dependencias mágicas.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.dependencies import require_page_roles, DbSession

logger = logging.getLogger("itcj2.apps.agendatec.pages.student")

router = APIRouter(prefix="/student", tags=["agendatec-pages-student"])

_require_student = require_page_roles("agendatec", ["student"])


def _is_window_open() -> bool:
    from itcj2.apps.agendatec.utils.period_utils import is_student_window_open
    return is_student_window_open()


@router.get("/home", name="agendatec.pages.student.home")
async def student_home(
    request: Request,
    user: dict = Depends(_require_student),
    db: DbSession = None,
):
    """Home del estudiante — redirige a /close si la ventana está cerrada."""
    if not _is_window_open():
        return RedirectResponse("/agendatec/student/close", status_code=302)

    from itcj2.apps.agendatec.services.student.home import has_request

    user_id = int(user["sub"])
    has_appt = has_request(db, user_id)

    return render_agendatec(request, "agendatec/student/home.html", {
        "title": "Alumno - Inicio",
        "has_appointment": has_appt,
    })


@router.get("/requests", name="agendatec.pages.student.requests")
async def student_requests(
    request: Request,
    user: dict = Depends(_require_student),
):
    """Lista de solicitudes del estudiante (accesible con ventana abierta o cerrada)."""
    return render_agendatec(request, "agendatec/student/requests.html", {
        "title": "Alumno - Mis solicitudes",
    })


@router.get("/request", name="agendatec.pages.student.new_request")
async def student_new_request(
    request: Request,
    user: dict = Depends(_require_student),
):
    """Formulario de nueva solicitud — redirige a /close si la ventana está cerrada."""
    if not _is_window_open():
        return RedirectResponse("/agendatec/student/close", status_code=302)

    return render_agendatec(request, "agendatec/student/new_request.html", {
        "title": "Alumno - Nueva solicitud",
    })


@router.get("/close", name="agendatec.pages.student.close")
async def student_close(
    request: Request,
    user: dict = Depends(_require_student),
):
    """Página de ventana cerrada — redirige a /home si la ventana ya está abierta."""
    if _is_window_open():
        return RedirectResponse("/agendatec/student/home", status_code=302)

    from itcj2.apps.agendatec.utils.period_utils import (
        fmt_spanish,
        get_student_window,
        get_window_status,
    )

    start, end = get_student_window()
    status = get_window_status()

    return render_agendatec(request, "agendatec/student/close.html", {
        "win_from": fmt_spanish(start),
        "win_to": fmt_spanish(end),
        "window_status": status,
    })
