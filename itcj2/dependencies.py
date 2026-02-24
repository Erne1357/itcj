from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db

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

        from itcj.core.services.authz_service import has_any_assignment

        user_id = int(user["sub"])
        if not has_any_assignment(user_id, app_key):
            raise HTTPException(
                status_code=403,
                detail=f"Sin acceso a la aplicación: {app_key}",
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

        from itcj.core.services.authz_service import user_roles_in_app

        user_id = int(user["sub"])
        user_roles = set(user_roles_in_app(user_id, app_key))

        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requiere rol: {', '.join(roles)}",
            )
        return user

    return Depends(dependency)
