"""Acceso propio de Prórrogas: un permiso por pestaña.

`require_page_app` es compartida y rechaza al admin global que no tiene rol en la app,
así que aquí se resuelve por separado.
"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import is_global_admin
from itcj2.exceptions import PageForbidden, PageLoginRequired

APP_KEY = "prorrogas_tec"


def perms_of(db: Session, user: dict) -> set[str]:
    """Permisos del usuario en la app; `{"*"}` solo para el admin global."""
    if is_global_admin(user):
        return {"*"}
    from itcj2.core.services.authz_cache import cached_perms

    return cached_perms(db, int(user["sub"]), APP_KEY)


def require_tab(code: str):
    """Sin sesión → login; sin la app o sin `code` → 403. Deja los permisos en `request.state`."""

    def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()
        if not is_global_admin(user):
            from itcj2.core.services.authz_cache import cached_has_assignment

            if not cached_has_assignment(db, int(user["sub"]), APP_KEY):
                raise PageForbidden(has_app_access=False)
        perms = perms_of(db, user)
        if "*" not in perms and code not in perms:
            raise PageForbidden(has_app_access=True)
        request.state.prorrogas_perms = perms
        return user

    return dependency
