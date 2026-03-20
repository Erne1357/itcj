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

        from itcj2.core.services.authz_service import user_roles_in_app

        uid = int(user["sub"])
        if not _roles_set & set(user_roles_in_app(db, uid, app_key)):
            raise PageForbidden()

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

        from itcj2.core.services.authz_service import (
            get_user_permissions_for_app,
            has_any_assignment,
        )

        uid = int(user["sub"])

        if not has_any_assignment(db, uid, app_key):
            raise PageForbidden()

        if _perms_set:
            user_perms = get_user_permissions_for_app(db, uid, app_key)
            if not (_perms_set & user_perms):
                raise PageForbidden()

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

        from itcj2.core.services.authz_service import has_any_assignment

        user_id = int(user["sub"])
        if not has_any_assignment(db, user_id, app_key):
            raise HTTPException(
                status_code=403,
                detail=f"Sin acceso a la aplicación: {app_key}",
            )
        return user

    return Depends(dependency)


def require_perms(app_key: str, perms: list[str]):
    """Equivale a @api_app_required("helpdesk", perms=[...]) de Flask.

    Replica la lógica de ``_check_app_access_enhanced`` del decorador Flask:
    1. Admin global (JWT role == "admin") bypasses todo.
    2. Verifica ``has_any_assignment(uid, app_key, include_positions=True)``.
    3. Verifica ``get_user_permissions_for_app`` contra *perms* requeridos.

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
        if user.get("role") == "admin":
            return user

        from itcj2.core.services.authz_service import (
            has_any_assignment,
            get_user_permissions_for_app,
        )

        uid = int(user["sub"])

        if not has_any_assignment(db, uid, app_key, include_positions=True):
            raise HTTPException(
                status_code=403,
                detail=f"Sin acceso a la aplicación: {app_key}",
            )

        user_perm_set = get_user_permissions_for_app(
            db, uid, app_key, include_positions=True
        )
        if not (_perms_set & user_perm_set):
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

        from itcj2.core.services.authz_service import user_roles_in_app

        user_id = int(user["sub"])
        user_roles = set(user_roles_in_app(db, user_id, app_key))

        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requiere rol: {', '.join(roles)}",
            )
        return user

    return Depends(dependency)
