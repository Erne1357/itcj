"""Páginas de ayuda (manual de usuario) para Mantenimiento.

El acceso es 100% granular por permiso (`maint.help.page.{requester|admin|tech}`).
Solo el rol "admin" de la app maint (que incluye al jefe de mantenimiento, admin
vía su puesto) bypassa los perms y ve las 3 vistas. Ser admin GLOBAL del sistema
NO basta: un jefe de otro departamento ve solo la guía de solicitante.

A diferencia de `require_page_app`, estas rutas **no lanzan 403** cuando el
usuario no tiene el perm de esa vista: redirigen (302) a la primera vista de
ayuda que sí pueda ver. Solo si no tiene ninguna se lanza ``PageForbidden``.
Esto evita que el botón "Ayuda" del nav mande a una ruta sin permiso.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.exceptions import PageForbidden, PageLoginRequired
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-help"])

# Orden de preferencia al redirigir: el usuario aterriza en la primera que pueda.
_VIEW_URL = {
    "requester": "/maint/help",
    "admin": "/maint/help/admin",
    "tech": "/maint/help/tech",
}
_VIEW_PERM = {
    "requester": "maint.help.page.requester",
    "admin": "maint.help.page.admin",
    "tech": "maint.help.page.tech",
}
_VIEW_ORDER = ("requester", "admin", "tech")


def _resolve_help_access(request: Request, db: Session):
    """Devuelve (user, allowed: dict[str,bool], best_url: str|None).

    `allowed` indica qué vistas puede ver el usuario. `best_url` es la URL de
    la primera vista permitida según `_VIEW_ORDER` (None si ninguna).
    """
    user = getattr(request.state, "current_user", None)
    if not user:
        raise PageLoginRequired()

    from itcj2.core.services.authz_service import (
        get_user_permissions_for_app,
        has_any_assignment,
        user_roles_in_app,
    )

    uid = int(user["sub"])
    if not has_any_assignment(db, uid, "maint"):
        raise PageForbidden()

    try:
        roles = set(user_roles_in_app(db, uid, "maint"))
    except Exception:
        roles = set()
    # Solo el rol ADMIN de la app maint (incluye al jefe de mantenimiento, admin
    # vía su puesto) ve las 3 vistas. Admin GLOBAL del sistema NO basta — un jefe
    # de otro departamento solo ve la guía de solicitante (su permiso real).
    is_maint_admin = ("admin" in roles)

    perms = get_user_permissions_for_app(db, uid, "maint")
    allowed = {
        v: (is_maint_admin or _VIEW_PERM[v] in perms) for v in _VIEW_ORDER
    }
    best_url = next(
        (_VIEW_URL[v] for v in _VIEW_ORDER if allowed[v]), None
    )
    return user, allowed, best_url


def _serve(request: Request, db: Session, view: str, template: str, title: str):
    """Sirve la vista pedida o redirige a la mejor permitida."""
    _, allowed, best_url = _resolve_help_access(request, db)

    if not allowed[view]:
        if best_url is None:
            raise PageForbidden()
        return RedirectResponse(url=best_url, status_code=302)

    return render_maint(request, template, {
        "page_title": title,
        "active_view": view,
    })


@router.get("/help", name="maint_pages.help_requester")
async def help_requester(request: Request, db: Session = Depends(get_db)):
    """Manual para solicitantes."""
    return _serve(
        request, db, "requester",
        "maint/help/requester.html", "Ayuda — Solicitantes",
    )


@router.get("/help/admin", name="maint_pages.help_admin")
async def help_admin(request: Request, db: Session = Depends(get_db)):
    """Manual para admin y dispatchers."""
    return _serve(
        request, db, "admin",
        "maint/help/admin.html", "Ayuda — Admin / Dispatcher",
    )


@router.get("/help/tech", name="maint_pages.help_tech")
async def help_tech(request: Request, db: Session = Depends(get_db)):
    """Manual para técnicos."""
    return _serve(
        request, db, "tech",
        "maint/help/tech.html", "Ayuda — Técnicos",
    )
