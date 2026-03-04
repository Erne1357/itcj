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
  POST /itcj/config/email/auth/logout            → Desconectar cuenta de correo (AJAX)
  GET  /itcj/config/email/auth/status            → Estado de conexión de correo (AJAX)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_

from itcj2.dependencies import require_page_login
from itcj2.exceptions import PageForbidden

logger = logging.getLogger("itcj2.core.pages.config")

router = APIRouter(tags=["core-pages-config"])


# ---------------------------------------------------------------------------
# Helper de autorización de admin (no es una dependencia de FastAPI para poder
# llamarla desde dentro del handler con la información ya disponible)
# ---------------------------------------------------------------------------


def _assert_admin(user: dict) -> None:
    """Lanza PageForbidden si el usuario no tiene rol admin en itcj."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    _db = SessionLocal()
    try:
        if "admin" not in user_roles_in_app(_db, uid, "itcj"):
            raise PageForbidden()
    finally:
        _db.close()


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------


@router.get("/config", name="core.pages.config.settings")
async def settings(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Panel principal de configuración del sistema."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.core.models.department import Department
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        apps = _db.query(App).order_by(App.key.asc()).all()
        roles = _db.query(Role).order_by(Role.name.asc()).all()
        users_count = _db.query(User).count()
        permissions_count = _db.query(Permission).count()
        departments_count = _db.query(Department).filter_by(is_active=True).count()

        themes_count = 0
        active_theme_name = None
        try:
            from itcj2.core.models.theme import Theme
            from itcj2.core.services import themes_service

            themes_count = _db.query(Theme).filter_by(is_enabled=True).count()
            active = themes_service.get_active_theme()
            if active:
                active_theme_name = active.name
        except Exception:
            pass

        return render(request, "core/config/index.html", {
            "apps": apps,
            "roles": roles,
            "users_count": users_count,
            "permissions_count": permissions_count,
            "departments_count": departments_count,
            "themes_count": themes_count,
            "active_theme_name": active_theme_name,
        })
    finally:
        _db.close()


# ---------------------------------------------------------------------------
# Sistema: apps, roles, permisos, temas
# ---------------------------------------------------------------------------


@router.get("/config/apps", name="core.pages.config.apps_management")
async def apps_management(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de gestión de aplicaciones."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        apps = _db.query(App).order_by(App.key.asc()).all()
        return render(request, "core/config/system/apps.html", {"apps": apps})
    finally:
        _db.close()


@router.get("/config/roles", name="core.pages.config.roles_management")
async def roles_management(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de gestión de roles globales."""
    _assert_admin(user)

    from itcj2.core.models.role import Role
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        roles = _db.query(Role).order_by(Role.name.asc()).all()
        return render(request, "core/config/system/roles.html", {"roles": roles})
    finally:
        _db.close()


@router.get("/config/apps/{app_key}/permissions", name="core.pages.config.app_permissions")
async def app_permissions(
    request: Request,
    app_key: str,
    user: dict = Depends(require_page_login),
):
    """Página de gestión de permisos de una app específica."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.core.models.permission import Permission
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        app = _db.query(App).filter_by(key=app_key).first()
        if not app:
            raise HTTPException(status_code=404, detail="App no encontrada")

        permissions = (
            _db.query(Permission)
            .filter_by(app_id=app.id)
            .order_by(Permission.code.asc())
            .all()
        )
        return render(request, "core/config/system/permissions.html", {
            "app": app,
            "permissions": permissions,
        })
    finally:
        _db.close()


@router.get("/config/themes", name="core.pages.config.themes_management")
async def themes_management(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de gestión de temas visuales del sistema."""
    _assert_admin(user)

    from itcj2.templates import render

    return render(request, "core/config/system/themes.html")


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


@router.get("/config/users", name="core.pages.config.users_management")
async def users_management(
    request: Request,
    user: dict = Depends(require_page_login),
    page: int = Query(1, ge=1, description="Página actual"),
    q: str = Query("", description="Término de búsqueda"),
):
    """Página de gestión de usuarios con paginación y búsqueda."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal
    from itcj2.models.base import paginate
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        per_page = 20
        users_query = _db.query(User)

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
        apps = _db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
        roles = _db.query(Role).order_by(Role.name.asc()).all()

        return render(request, "core/config/users/users.html", {
            "users": pagination.items,
            "apps": apps,
            "roles": roles,
            "pagination": pagination,
            "current_query": q,
        })
    finally:
        _db.close()


@router.get("/config/users/{user_id}", name="core.pages.config.user_detail")
async def user_detail(
    request: Request,
    user_id: int,
    user: dict = Depends(require_page_login),
):
    """Página de detalle de un usuario con sus asignaciones."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        target = _db.get(User, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        apps = _db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
        roles = _db.query(Role).order_by(Role.name.asc()).all()

        return render(request, "core/config/users/user_detail.html", {
            "user": target,
            "apps": apps,
            "roles": roles,
        })
    finally:
        _db.close()


# ---------------------------------------------------------------------------
# Organización: departamentos y puestos
# ---------------------------------------------------------------------------


@router.get("/config/departments", name="core.pages.config.positions_management")
async def positions_management(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Vista principal de departamentos y estructura organizacional."""
    _assert_admin(user)

    from itcj2.templates import render

    return render(request, "core/config/organization/departments.html")


@router.get("/config/departments/{department_id}", name="core.pages.config.department_detail")
async def department_detail(
    request: Request,
    department_id: int,
    user: dict = Depends(require_page_login),
):
    """Vista de detalle de un departamento con sus puestos."""
    _assert_admin(user)

    from itcj2.core.models.department import Department
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        dept = _db.get(Department, department_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Departamento no encontrado")

        return render(request, "core/config/organization/department_detail.html", {
            "department_id": department_id,
            "department": dept,
        })
    finally:
        _db.close()


@router.get("/config/positions/{position_id}", name="core.pages.config.position_detail")
async def position_detail(
    request: Request,
    position_id: int,
    user: dict = Depends(require_page_login),
):
    """Vista de detalle y edición de un puesto."""
    _assert_admin(user)

    from itcj2.core.models.position import Position
    from itcj2.core.models.role import Role
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        position = _db.get(Position, position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Puesto no encontrado")

        roles = _db.query(Role).order_by(Role.name.asc()).all()

        return render(request, "core/config/organization/position_detail.html", {
            "position_id": position_id,
            "position": position,
            "roles": roles,
        })
    finally:
        _db.close()


# ---------------------------------------------------------------------------
# Correo: OAuth con Microsoft (Microsoft Graph)
# ---------------------------------------------------------------------------


@router.get("/config/email", name="core.pages.config.email_management")
async def email_management(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de configuración de cuentas de correo por aplicación."""
    _assert_admin(user)

    from itcj2.core.models.app import App
    from itcj2.core.utils import msgraph_mail
    from itcj2.database import SessionLocal
    from itcj2.templates import render

    _db = SessionLocal()
    try:
        apps = _db.query(App).filter_by(is_active=True).order_by(App.key.asc()).all()
        apps_email = [
            {
                "key": app.key,
                "name": app.name,
                "connected": (acct := msgraph_mail.read_account_info(app.key)) is not None,
                "username": acct.get("username") if acct else None,
                "account_name": acct.get("name") if acct else None,
            }
            for app in apps
        ]
        return render(request, "core/config/system/email.html", {"apps_email": apps_email})
    finally:
        _db.close()


@router.get("/config/email/auth/login", name="core.pages.config.email_auth_login")
async def email_auth_login(
    request: Request,
    app: str = Query("", description="App key a conectar"),
    user: dict = Depends(require_page_login),
):
    """Inicia el flujo OAuth con Microsoft para la app indicada."""
    _assert_admin(user)

    from itcj2.core.models.app import App as AppModel
    from itcj2.core.utils import msgraph_mail
    from itcj2.database import SessionLocal

    if not app:
        return RedirectResponse("/itcj/config/email", status_code=302)

    _db = SessionLocal()
    try:
        app_obj = _db.query(AppModel).filter_by(key=app, is_active=True).first()
    finally:
        _db.close()
    if not app_obj:
        logger.warning("email_auth_login: app '%s' no encontrada", app)
        return RedirectResponse("/itcj/config/email", status_code=302)

    auth_url = msgraph_mail.build_auth_url(app)
    return RedirectResponse(auth_url, status_code=302)


@router.get("/config/email/auth/callback", name="core.pages.config.email_auth_callback")
async def email_auth_callback(
    request: Request,
    code: str = Query("", description="Código de autorización de Microsoft"),
    state: str = Query("", description="App key (enviado como 'state' en el flujo OAuth)"),
):
    """Callback OAuth de Microsoft. Intercambia el código por tokens y guarda la cuenta."""
    from itcj2.core.utils import msgraph_mail

    if not code or not state:
        logger.warning("email_auth_callback: faltan parámetros code o state")
        return RedirectResponse("/itcj/config/email", status_code=302)

    result = msgraph_mail.process_auth_code(state, code)
    if result.get("error"):
        logger.error(
            "email_auth_callback error para app '%s': %s",
            state,
            result.get("error_description", result["error"]),
        )

    return RedirectResponse("/itcj/config/email", status_code=302)


@router.post("/config/email/auth/logout", name="core.pages.config.email_auth_logout")
async def email_auth_logout(
    request: Request,
    app: str = Query("", description="App key a desconectar"),
    user: dict = Depends(require_page_login),
):
    """Desconecta la cuenta de correo de una app (endpoint AJAX)."""
    _assert_admin(user)

    if not app:
        return JSONResponse({"ok": False, "error": "Falta parámetro 'app'"}, status_code=400)

    from itcj2.core.utils import msgraph_mail

    msgraph_mail.clear_account_and_cache(app)
    return JSONResponse({"ok": True})


@router.get("/config/email/auth/status", name="core.pages.config.email_auth_status")
async def email_auth_status(
    request: Request,
    app: str = Query("", description="App key a consultar"),
    user: dict = Depends(require_page_login),
):
    """Retorna el estado de conexión de correo de una app (endpoint AJAX)."""
    _assert_admin(user)

    if not app:
        return JSONResponse({"connected": False, "error": "Falta parámetro 'app'"}, status_code=400)

    from itcj2.core.utils import msgraph_mail

    token = msgraph_mail.acquire_token_silent(app)
    acct = msgraph_mail.read_account_info(app)
    return JSONResponse({"connected": bool(token), "account": acct})
