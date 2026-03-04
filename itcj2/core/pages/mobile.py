"""
Páginas del dashboard móvil (equivalente a itcj/core/routes/pages/mobile.py).

Rutas:
  GET /itcj/m/               → Dashboard móvil (detecta tipo de usuario)
  GET /itcj/m/notifications  → Notificaciones en vista móvil
  GET /itcj/m/profile        → Perfil en vista móvil
  GET /itcj/m/switch-desktop → Guarda cookie prefer_desktop y redirige al dashboard
  GET /itcj/m/switch-mobile  → Elimina cookie prefer_desktop y redirige al móvil
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import DbSession, require_page_login
from itcj2.templates import render

logger = logging.getLogger("itcj2.core.pages.mobile")

router = APIRouter(prefix="/m", tags=["core-pages-mobile"])


@router.get("", include_in_schema=False)
@router.get("/", name="core.pages.mobile.dashboard")
async def mobile_dashboard(
    request: Request,
    user: dict = Depends(require_page_login),
    db: DbSession = None,
):
    """Dashboard móvil: estudiantes ven vista de alumno, staff ve vista de personal."""
    from itcj2.core.services.mobile_service import (
        get_mobile_apps_for_user,
        get_user_for_mobile,
        get_user_type,
    )

    user_id = int(user["sub"])
    mobile_user = get_user_for_mobile(db, user_id)
    user_type = get_user_type(db, user_id)
    apps = get_mobile_apps_for_user(db, user_id)

    if user_type == "student":
        return render(request, "core/mobile/student_dashboard.html", {
            "user": mobile_user,
            "user_type": user_type,
            "apps": apps,
            "active_tab": "home",
        })

    quick_actions = _build_quick_actions(user_id)
    return render(request, "core/mobile/staff_dashboard.html", {
        "user": mobile_user,
        "user_type": user_type,
        "apps": apps,
        "quick_actions": quick_actions,
        "active_tab": "home",
    })


@router.get("/notifications", name="core.pages.mobile.notifications")
async def mobile_notifications(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de notificaciones en vista móvil."""
    from itcj2.core.services.mobile_service import get_user_type

    user_id = int(user["sub"])
    user_type = get_user_type(user_id)

    return render(request, "core/mobile/notifications.html", {
        "user_type": user_type,
        "active_tab": "notifications",
    })


@router.get("/profile", name="core.pages.mobile.profile")
async def mobile_profile(
    request: Request,
    user: dict = Depends(require_page_login),
    db: DbSession = None,
):
    """Perfil en vista móvil: simplificado para estudiantes, completo para staff."""
    from itcj2.core.services.mobile_service import get_user_for_mobile, get_user_type

    user_id = int(user["sub"])
    mobile_user = get_user_for_mobile(db, user_id)
    user_type = get_user_type(db, user_id)

    if user_type == "student":
        return render(request, "core/mobile/student_profile.html", {
            "user": mobile_user,
            "user_type": user_type,
            "active_tab": "profile",
        })

    return render(request, "core/mobile/staff_profile.html", {
        "user": mobile_user,
        "user_type": user_type,
        "active_tab": "profile",
    })


@router.get("/switch-desktop", name="core.pages.mobile.switch_desktop")
async def mobile_switch_desktop(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Guarda la preferencia de vista desktop (cookie) y redirige al dashboard."""
    response = RedirectResponse("/itcj/dashboard", status_code=302)
    response.set_cookie(
        "prefer_desktop",
        "1",
        max_age=30 * 24 * 3600,
        samesite="lax",
        httponly=False,
        path="/",
    )
    return response


@router.get("/switch-mobile", name="core.pages.mobile.switch_mobile")
async def mobile_switch_mobile(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Elimina la preferencia de vista desktop y redirige al dashboard móvil."""
    response = RedirectResponse("/itcj/m/", status_code=302)
    response.delete_cookie("prefer_desktop", path="/")
    return response


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _build_quick_actions(user_id: int) -> list[dict]:
    """Construye la lista de accesos rápidos para staff según sus roles."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    actions: list[dict] = []
    _db = SessionLocal()
    try:
        roles_itcj = user_roles_in_app(_db, user_id, "itcj")
        if "admin" in roles_itcj:
            actions.append({
                "label": "Configuración",
                "url": "/itcj/config",
                "icon": "bi-gear",
            })

        try:
            if user_roles_in_app(_db, user_id, "helpdesk"):
                actions.append({
                    "label": "Tickets",
                    "url": "/help-desk/",
                    "icon": "bi-ticket-detailed",
                })
        except Exception:
            pass

        try:
            roles_agenda = user_roles_in_app(_db, user_id, "agendatec")
            if roles_agenda - {"student"}:
                actions.append({
                    "label": "AgendaTec",
                    "url": "/agendatec/",
                    "icon": "bi-calendar-check",
                })
        except Exception:
            pass
    finally:
        _db.close()

    return actions
