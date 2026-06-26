from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .exceptions import PageForbidden, PageLoginRequired

# ---------------------------------------------------------------------------
# Tipo reutilizable para inyección de DB
# ---------------------------------------------------------------------------
DbSession = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------
def get_current_user(request: Request) -> dict:
    """Requiere usuario autenticado. Equivale a @login_required de Flask."""
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def get_current_user_optional(request: Request) -> dict | None:
    """Retorna el usuario si hay sesión, None si no."""
    return getattr(request.state, "current_user", None)


CurrentUser = Annotated[dict, Depends(get_current_user)]
OptionalUser = Annotated[dict | None, Depends(get_current_user_optional)]


# ---------------------------------------------------------------------------
# Page dependencies (redirigen en lugar de retornar JSON de error)
# ---------------------------------------------------------------------------


def require_page_login(request: Request) -> dict:
    """Requiere autenticación para páginas HTML.

    Equivale a @login_required de Flask pero lanza ``PageLoginRequired``
    en lugar de 401 JSON. El exception handler en main.py redirige a
    ``/itcj/login``.
    """
    user = getattr(request.state, "current_user", None)
    if not user:
        raise PageLoginRequired()
    return user


def require_page_roles(app_key: str, roles: list[str]):
    """Dependencia factory para páginas que requieren un rol específico en una app.

    Lanza ``PageLoginRequired`` si no hay sesión y ``PageForbidden`` si
    el usuario no tiene ninguno de los roles requeridos.

    Uso::

        @router.get("/agendatec/student/home")
        async def student_home(user: dict = require_page_roles("agendatec", ["student"])):
            ...
    """
    _roles_set = set(roles)

    def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()

        from itcj2.core.services.authz_cache import cached_roles, cached_has_assignment

        uid = int(user["sub"])
        if not _roles_set & cached_roles(db, uid, app_key):
            # Tiene acceso a la app pero no el rol de esta página →
            # botón al inicio de la app. Sin acceso → panel core.
            raise PageForbidden(
                has_app_access=cached_has_assignment(db, uid, app_key)
            )

        return user

    return dependency


def require_page_app(app_key: str, perms: list[str] | None = None):
    """Dependencia factory para páginas que requieren acceso a una app.

    Lanza ``PageLoginRequired`` si no hay sesión y ``PageForbidden`` si
    el usuario no tiene acceso a la app o los permisos requeridos.

    Uso::

        @router.get("/help-desk/user/create")
        async def create_ticket(user: dict = require_page_app("helpdesk")):
            ...
    """
    _perms_set = set(perms) if perms else set()

    def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()

        from itcj2.core.services.authz_cache import cached_has_assignment, cached_perms

        uid = int(user["sub"])

        if not cached_has_assignment(db, uid, app_key):
            # Sin acceso a la app → panel core (no hay inicio de app).
            raise PageForbidden(has_app_access=False)

        if _perms_set:
            if not (_perms_set & cached_perms(db, uid, app_key)):
                # Tiene la app pero le falta el permiso de esta página →
                # botón al inicio de la app.
                raise PageForbidden(has_app_access=True)

        return user

    return dependency


# ---------------------------------------------------------------------------
# App/role authorization dependencies
# ---------------------------------------------------------------------------
def require_app(app_key: str):
    """Equivale a @app_required("helpdesk") de Flask.

    Uso:
        @router.get("/")
        async def endpoint(user: dict = require_app("helpdesk")):
            ...
    """
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="No autenticado")

        from itcj2.core.services.authz_cache import cached_has_assignment

        user_id = int(user["sub"])
        if not cached_has_assignment(db, user_id, app_key):
            raise HTTPException(
                status_code=403,
                detail=f"Sin acceso a la aplicación: {app_key}",
            )
        return user

    return Depends(dependency)


def require_perms(app_key: str, perms: list[str], *, allow_global_admin: bool = True):
    """Equivale a @api_app_required("helpdesk", perms=[...]) de Flask.

    Replica la lógica de ``_check_app_access_enhanced`` del decorador Flask:
    1. Admin global (JWT role == "admin") bypasses todo.
    2. Verifica ``has_any_assignment(uid, app_key, include_positions=True)``.
    3. Verifica ``get_user_permissions_for_app`` contra *perms* requeridos.

    ``allow_global_admin=False`` desactiva el bypass del admin global del JWT (1):
    el usuario debe tener el PERMISO real en la app. Se usa en acciones
    operativas reservadas a roles reales (p.ej. resolver/enrutar/asignar en
    maint) para que un admin global del sistema que NO es operador de la app
    no las ejecute. Ver auditoría maint: "admin global del sistema ≠ operador".

    Uso::

        @router.get("/tickets")
        def list_tickets(user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"])):
            ...
    """
    _perms_set = set(perms)

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="No autenticado")

        # Admin global por rol del JWT
        if allow_global_admin and user.get("role") == "admin":
            return user

        from itcj2.core.services.authz_cache import cached_has_assignment, cached_perms

        uid = int(user["sub"])

        if not cached_has_assignment(db, uid, app_key):
            raise HTTPException(
                status_code=403,
                detail=f"Sin acceso a la aplicación: {app_key}",
            )

        if not (_perms_set & cached_perms(db, uid, app_key)):
            raise HTTPException(
                status_code=403,
                detail=f"Requiere permiso: {', '.join(perms)}",
            )
        return user

    return Depends(dependency)


def require_roles(app_key: str, roles: list[str]):
    """Equivale a @app_required_enhanced("helpdesk", roles=["admin"]).

    Uso:
        @router.get("/admin")
        async def endpoint(user: dict = require_roles("helpdesk", ["admin"])):
            ...
    """
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="No autenticado")

        from itcj2.core.services.authz_cache import cached_roles

        user_id = int(user["sub"])
        user_roles = cached_roles(db, user_id, app_key)

        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requiere rol: {', '.join(roles)}",
            )
        return user

    return Depends(dependency)
