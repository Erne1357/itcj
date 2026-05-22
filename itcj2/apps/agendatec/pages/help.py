"""Páginas de ayuda (manual de usuario) para AgendaTec.

Acceso 100% granular por permiso (`agendatec.help.page.{student|coord|social|admin}`).
Admin (rol agendatec "admin" o admin global del JWT) bypassa los perms.

Patrón redirect-on-no-access: si el usuario pide una vista sin permiso, se le
redirige (302) a la primera vista de ayuda que sí pueda ver. Solo lanza
``PageForbidden`` si no tiene ninguna.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.database import get_db
from itcj2.exceptions import PageForbidden, PageLoginRequired

router = APIRouter(tags=["agendatec-help"])

# Orden de preferencia al redirigir: la primera permitida es la landing.
_VIEW_URL = {
    "student": "/agendatec/help",
    "coord": "/agendatec/help/coord",
    "social": "/agendatec/help/social",
    "admin": "/agendatec/help/admin",
}
_VIEW_PERM = {
    "student": "agendatec.help.page.student",
    "coord": "agendatec.help.page.coord",
    "social": "agendatec.help.page.social",
    "admin": "agendatec.help.page.admin",
}
_VIEW_ORDER = ("student", "coord", "social", "admin")


def _resolve_help_access(request: Request, db: Session):
    """Devuelve (user, allowed: dict[str,bool], best_url: str|None)."""
    user = getattr(request.state, "current_user", None)
    if not user:
        raise PageLoginRequired()

    from itcj2.core.services.authz_service import (
        get_user_permissions_for_app,
        has_any_assignment,
        user_roles_in_app,
    )

    uid = int(user["sub"])
    if not has_any_assignment(db, uid, "agendatec"):
        raise PageForbidden()

    try:
        roles = set(user_roles_in_app(db, uid, "agendatec"))
    except Exception:
        roles = set()
    is_admin = ("admin" in roles) or (str(user.get("role")) == "admin")

    perms = get_user_permissions_for_app(db, uid, "agendatec")
    allowed = {v: (is_admin or _VIEW_PERM[v] in perms) for v in _VIEW_ORDER}
    best_url = next((_VIEW_URL[v] for v in _VIEW_ORDER if allowed[v]), None)
    return user, allowed, best_url


def _serve(request: Request, db: Session, view: str, template: str, title: str):
    """Sirve la vista pedida o redirige a la mejor permitida."""
    _, allowed, best_url = _resolve_help_access(request, db)

    if not allowed[view]:
        if best_url is None:
            raise PageForbidden()
        return RedirectResponse(url=best_url, status_code=302)

    return render_agendatec(request, template, {
        "page_title": title,
        "active_view": view,
        "help_perms": allowed,
    })


@router.get("/help", name="agendatec_pages.help_pages.help_student")
async def help_student(request: Request, db: Session = Depends(get_db)):
    """Manual del estudiante (mobile-first)."""
    return _serve(
        request, db, "student",
        "agendatec/help/student.html", "Ayuda — Estudiante",
    )


@router.get("/help/coord", name="agendatec_pages.help_pages.help_coord")
async def help_coord(request: Request, db: Session = Depends(get_db)):
    """Manual del coordinador."""
    return _serve(
        request, db, "coord",
        "agendatec/help/coord.html", "Ayuda — Coordinador",
    )


@router.get("/help/social", name="agendatec_pages.help_pages.help_social")
async def help_social(request: Request, db: Session = Depends(get_db)):
    """Manual de servicio social."""
    return _serve(
        request, db, "social",
        "agendatec/help/social.html", "Ayuda — Servicio Social",
    )


@router.get("/help/admin", name="agendatec_pages.help_pages.help_admin")
async def help_admin(request: Request, db: Session = Depends(get_db)):
    """Manual del administrador."""
    return _serve(
        request, db, "admin",
        "agendatec/help/admin.html", "Ayuda — Administrador",
    )
