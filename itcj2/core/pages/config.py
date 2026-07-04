"""
Páginas del panel de configuración del sistema (solo admin).
Equivalente a itcj/core/routes/pages/config.py.

Rutas:
  GET  /itcj/config                              → Panel principal
  GET  /itcj/config/apps                         → Gestión de apps
  GET  /itcj/config/roles                        → Gestión de roles
  GET  /itcj/config/apps/{app_key}/permissions   → Permisos de una app
  GET  /itcj/config/themes                       → Gestión de temas
  GET  /itcj/config/users                        → Gestión de usuarios
  GET  /itcj/config/users/{user_id}              → Detalle de usuario
  GET  /itcj/config/departments                  → Departamentos y puestos
  GET  /itcj/config/departments/{dept_id}        → Detalle de departamento
  GET  /itcj/config/positions/{pos_id}           → Detalle de puesto
  GET  /itcj/config/email                        → Gestión de cuentas de correo
  GET  /itcj/config/email/auth/login             → Iniciar OAuth con Microsoft
  GET  /itcj/config/email/auth/callback          → Callback OAuth de Microsoft
  (Los AJAX status/logout viven en /api/core/v2/email — ver itcj2/core/api/email.py)
  GET  /itcj/config/system/tasks                 → Tareas programadas

Autorización (F1a core-config-revamp): todas las páginas usan
require_page_roles("itcj", ["admin"]) — rol admin en BD vía authz_cache; el
claim JWT NO bypasea. El guard en-handler legacy (ver historial git) se eliminó.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_

from itcj2.dependencies import DbSession, require_page_roles

logger = logging.getLogger("itcj2.core.pages.config")

router = APIRouter(tags=["core-pages-config"])

# Guard compartido: PageLoginRequired sin sesión (302 a login) y PageForbidden
# sin rol admin en itcj (página 403). Ver itcj2/dependencies.py:70-101.
_ADMIN_PAGE = Depends(require_page_roles("itcj", ["admin"]))


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------


@router.get("/config", name="core.pages.config.settings")
async def settings(
    request: Request,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Panel principal de configuración del sistema."""
    from itcj2.core.models.app import App
    from itcj2.core.models.department import Department
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.core.pages.nav_config import render_config

    apps = db.query(App).order_by(App.key.asc()).all()
    roles = db.query(Role).order_by(Role.name.asc()).all()
    users_count = db.query(User).count()
    permissions_count = db.query(Permission).count()
    departments_count = db.query(Department).filter_by(is_active=True).count()

    themes_count = 0
    active_theme_name = None
    try:
        from itcj2.core.models.theme import Theme
        from itcj2.core.services import themes_service

        themes_count = db.query(Theme).filter_by(is_enabled=True).count()
        active = themes_service.get_active_theme(db)
        if active:
            active_theme_name = active.name
    except Exception:
        pass

    return render_config(request, "core/config/index.html", "index", {
        "apps": apps,
        "roles": roles,
        "users_count": users_count,
        "permissions_count": permissions_count,
        "departments_count": departments_count,
        "themes_count": themes_count,
        "active_theme_name": active_theme_name,
    })


# ---------------------------------------------------------------------------
# Sistema: apps, roles, permisos, temas
# ---------------------------------------------------------------------------


@router.get("/config/apps", name="core.pages.config.apps_management")
async def apps_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Página de gestión de aplicaciones."""
    from itcj2.core.models.app import App
    from itcj2.core.pages.nav_config import render_config

    apps = db.query(App).order_by(App.key.asc()).all()
    return render_config(request, "core/config/system/apps.html", "apps", {"apps": apps})


@router.get("/config/roles", name="core.pages.config.roles_management")
async def roles_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Página de gestión de roles globales."""
    from sqlalchemy import func

    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.core.pages.nav_config import render_config

    role_counts = dict(
        db.query(User.role_id, func.count(User.id))
        .filter(User.role_id.isnot(None))
        .group_by(User.role_id)
        .all()
    )
    roles = db.query(Role).order_by(Role.name.asc()).all()
    return render_config(
        request, "core/config/system/roles.html", "roles",
        {"roles": roles, "role_counts": role_counts},
    )


@router.get("/config/apps/{app_key}/permissions", name="core.pages.config.app_permissions")
async def app_permissions(
    request: Request,
    app_key: str,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Página de gestión de permisos de una app específica."""
    from itcj2.core.models.app import App
    from itcj2.core.models.permission import Permission
    from itcj2.core.pages.nav_config import render_config

    app = db.query(App).filter_by(key=app_key).first()
    if not app:
        raise HTTPException(status_code=404, detail="App no encontrada")

    permissions = (
        db.query(Permission)
        .filter_by(app_id=app.id)
        .order_by(Permission.code.asc())
        .all()
    )
    return render_config(
        request, "core/config/system/permissions.html", "permissions",
        {"app": app, "permissions": permissions, "cfg_data": {"app-key": app.key}},
    )


@router.get("/config/themes", name="core.pages.config.themes_management")
async def themes_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
):
    """Página de gestión de temas visuales del sistema."""
    from itcj2.core.pages.nav_config import render_config

    return render_config(request, "core/config/system/themes.html", "themes")


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


@router.get("/config/users", name="core.pages.config.users_management")
async def users_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
    page: int = Query(1, ge=1, description="Página actual"),
    q: str = Query("", description="Término de búsqueda"),
):
    """Página de gestión de usuarios con paginación y búsqueda."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.models.base import paginate
    from itcj2.core.pages.nav_config import render_config

    per_page = 20
    users_query = db.query(User)

    if q:
        term = f"%{q}%"
        users_query = users_query.filter(
            or_(
                User.full_name.ilike(term),
                User.username.ilike(term),
                User.control_number.ilike(term),
                User.email.ilike(term),
            )
        )

    pagination = paginate(users_query.order_by(User.full_name.asc()), page=page, per_page=per_page)
    apps = db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = db.query(Role).order_by(Role.name.asc()).all()

    return render_config(request, "core/config/users/users.html", "users", {
        "users": pagination.items,
        "apps": apps,
        "roles": roles,
        "pagination": pagination,
        "current_query": q,
    })


@router.get("/config/users/{user_id}", name="core.pages.config.user_detail")
async def user_detail(
    request: Request,
    user_id: int,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Página de detalle de un usuario con sus asignaciones."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.core.pages.nav_config import render_config

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    apps = db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = db.query(Role).order_by(Role.name.asc()).all()

    return render_config(request, "core/config/users/user_detail.html", "user_detail", {
        "user": target,
        "apps": apps,
        "roles": roles,
        "cfg_data": {"user-id": str(user_id)},
    })


# ---------------------------------------------------------------------------
# Organización: departamentos y puestos
# ---------------------------------------------------------------------------


@router.get("/config/departments", name="core.pages.config.positions_management")
async def positions_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
):
    """Vista principal de departamentos y estructura organizacional."""
    from itcj2.core.pages.nav_config import render_config

    return render_config(request, "core/config/organization/departments.html", "departments")


@router.get("/config/departments/{department_id}", name="core.pages.config.department_detail")
async def department_detail(
    request: Request,
    department_id: int,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Vista de detalle de un departamento con sus puestos."""
    from itcj2.core.models.department import Department
    from itcj2.core.pages.nav_config import render_config

    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")

    return render_config(
        request,
        "core/config/organization/department_detail.html",
        "department_detail",
        {
            "department": dept,
            "cfg_data": {"department-id": str(department_id)},
        },
    )


@router.get("/config/positions/{position_id}", name="core.pages.config.position_detail")
async def position_detail(
    request: Request,
    position_id: int,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Detalle y edición de un puesto."""
    from itcj2.core.models.position import Position
    from itcj2.core.pages.nav_config import render_config

    position = db.get(Position, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Puesto no encontrado")

    return render_config(
        request,
        "core/config/organization/position_detail.html",
        "position_detail",
        {
            "position": position,
            "cfg_data": {"position-id": str(position_id)},
        },
    )


# ---------------------------------------------------------------------------
# Correo: OAuth con Microsoft (Microsoft Graph)
# ---------------------------------------------------------------------------


@router.get("/config/email", name="core.pages.config.email_management")
async def email_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Página de configuración de cuentas de correo por aplicación."""
    from itcj2.core.models.app import App
    from itcj2.core.utils import msgraph_mail
    from itcj2.core.pages.nav_config import render_config

    apps = db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
    apps_email = [
        {
            "key": app.key,
            "name": app.name,
            "icon_class": app.icon_class,
            "color": app.color,
            "connected": (acct := msgraph_mail.read_account_info(app.key)) is not None,
            "username": acct.get("username") if acct else None,
            "account_name": acct.get("name") if acct else None,
        }
        for app in apps
    ]
    return render_config(request, "core/config/system/email.html", "email", {"apps_email": apps_email})


@router.get("/config/email/auth/login", name="core.pages.config.email_auth_login")
async def email_auth_login(
    request: Request,
    app: str = Query("", description="App key a conectar"),
    user: dict = _ADMIN_PAGE,
    db: DbSession = None,
):
    """Inicia el flujo OAuth con Microsoft para la app indicada.

    Genera un nonce anti-CSRF de un solo uso (C6): Redis oauth:state:{nonce}
    -> app_key con TTL EMAIL_OAUTH_STATE_TTL; el nonce viaja como ``state``.
    Redis caído => 500 (fail-closed, F1a-D6).
    """
    import secrets

    from itcj2.config import get_settings
    from itcj2.core.models.app import App as AppModel
    from itcj2.core.utils import msgraph_mail
    from itcj2.core.utils.redis_conn import get_redis

    if not app:
        return RedirectResponse("/itcj/config/email", status_code=302)

    app_obj = db.query(AppModel).filter_by(key=app, is_active=True).first()
    if not app_obj:
        logger.warning("email_auth_login: app '%s' no encontrada", app)
        return RedirectResponse("/itcj/config/email", status_code=302)

    nonce = secrets.token_urlsafe(32)
    get_redis().setex(
        f"oauth:state:{nonce}", get_settings().EMAIL_OAUTH_STATE_TTL, app
    )
    auth_url = msgraph_mail.build_auth_url(app, state=nonce)
    return RedirectResponse(auth_url, status_code=302)


@router.get("/config/email/auth/callback", name="core.pages.config.email_auth_callback")
async def email_auth_callback(
    request: Request,
    code: str = Query("", description="Código de autorización de Microsoft"),
    state: str = Query("", description="Nonce anti-CSRF emitido en email_auth_login"),
    user: dict = _ADMIN_PAGE,
):
    """Callback OAuth de Microsoft. Valida el nonce (un solo uso), resuelve el
    app_key desde Redis e intercambia el código por tokens (C6, security)."""
    from itcj2.core.utils import msgraph_mail
    from itcj2.core.utils.redis_conn import get_redis

    if not code or not state:
        logger.warning("email_auth_callback: faltan parámetros code o state")
        return RedirectResponse("/itcj/config/email", status_code=302)

    r = get_redis()
    redis_key = f"oauth:state:{state}"
    app_key = r.get(redis_key)
    if not app_key:
        logger.warning("email_auth_callback: state inválido o expirado")
        return RedirectResponse("/itcj/config/email", status_code=302)
    r.delete(redis_key)  # un solo uso

    result = msgraph_mail.process_auth_code(app_key, code)
    if result.get("error"):
        logger.error(
            "email_auth_callback error para app '%s': %s",
            app_key,
            result.get("error_description", result["error"]),
        )

    return RedirectResponse("/itcj/config/email", status_code=302)


@router.get("/config/system/tasks", name="core.pages.config.tasks_management")
async def tasks_management(
    request: Request,
    user: dict = _ADMIN_PAGE,
):
    """Página de gestión de tareas programadas (catálogo, schedules, historial)."""
    from itcj2.core.pages.nav_config import render_config

    return render_config(request, "core/config/system/tasks.html", "tasks")
