# itcj/core/routes/pages/mobile.py
"""
Rutas de paginas para el dashboard movil.
Accesible para estudiantes y staff.
"""
from flask import Blueprint, render_template, g, redirect, url_for, request, make_response
from itcj.core.utils.decorators import login_required
from itcj.core.services.mobile_service import (
    get_mobile_apps_for_user, get_user_type, get_user_for_mobile
)
from itcj.core.services.authz_service import user_roles_in_app

pages_mobile_bp = Blueprint("pages_mobile", __name__)


@pages_mobile_bp.get("/m")
@pages_mobile_bp.get("/m/")
@login_required
def mobile_dashboard():
    """Dashboard movil - detecta tipo de usuario y muestra la vista correspondiente."""
    user_id = int(g.current_user["sub"])
    user = get_user_for_mobile(user_id)
    user_type = get_user_type(user_id)
    apps = get_mobile_apps_for_user(user_id)

    if user_type == "student":
        return render_template(
            "core/mobile/student_dashboard.html",
            user=user,
            user_type=user_type,
            apps=apps,
            active_tab="home"
        )

    # Staff: construir quick actions basados en roles
    quick_actions = _build_quick_actions(user_id)

    return render_template(
        "core/mobile/staff_dashboard.html",
        user=user,
        user_type=user_type,
        apps=apps,
        quick_actions=quick_actions,
        active_tab="home"
    )


@pages_mobile_bp.get("/m/notifications")
@login_required
def mobile_notifications():
    """Pagina de notificaciones movil."""
    user_id = int(g.current_user["sub"])
    user_type = get_user_type(user_id)
    return render_template(
        "core/mobile/notifications.html",
        user_type=user_type,
        active_tab="notifications"
    )


@pages_mobile_bp.get("/m/switch-desktop")
@login_required
def mobile_switch_desktop():
    """Cambia a vista desktop - pone cookie y redirige."""
    resp = make_response(redirect(url_for('pages_core.pages_dashboard.dashboard')))
    resp.set_cookie('prefer_desktop', '1', max_age=30 * 24 * 3600,
                    samesite='Lax', httponly=False)
    return resp


@pages_mobile_bp.get("/m/switch-mobile")
@login_required
def mobile_switch_mobile():
    """Cambia a vista movil - borra cookie y redirige."""
    resp = make_response(redirect(url_for('pages_core.pages_mobile.mobile_dashboard')))
    resp.delete_cookie('prefer_desktop')
    return resp


def _build_quick_actions(user_id: int) -> list[dict]:
    """Construye lista de accesos rapidos para staff basandose en sus roles."""
    actions = []

    roles_itcj = user_roles_in_app(user_id, 'itcj')
    if 'admin' in roles_itcj:
        actions.append({
            "label": "Configuracion",
            "url": "/itcj/config",
            "icon": "bi-gear"
        })

    try:
        roles_helpdesk = user_roles_in_app(user_id, 'helpdesk')
        if roles_helpdesk:
            actions.append({
                "label": "Tickets",
                "url": "/help-desk/",
                "icon": "bi-ticket-detailed"
            })
    except Exception:
        pass

    try:
        roles_agendatec = user_roles_in_app(user_id, 'agendatec')
        non_student_roles = roles_agendatec - {"student"}
        if non_student_roles:
            actions.append({
                "label": "AgendaTec",
                "url": "/agendatec/",
                "icon": "bi-calendar-check"
            })
    except Exception:
        pass

    return actions
