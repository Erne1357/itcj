"""
Warehouse authorization helpers for helpdesk-integrated pages.

Because warehouse pages live INSIDE the helpdesk route tree, we cannot use
``require_page_app("warehouse", ...)`` directly (it would require an explicit
warehouse app assignment for every user). Instead we perform a cross-app
role-permission lookup: the user's helpdesk roles already have warehouse
permissions assigned via ``core_role_permissions``, so we query those
permissions through the helpdesk role assignment.
"""
from __future__ import annotations

import logging

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.exceptions import PageForbidden, PageLoginRequired

logger = logging.getLogger(__name__)


def get_warehouse_perms_via_helpdesk(db: Session, user_id: int) -> set[str]:
    """
    Return the set of warehouse permission codes that the user holds via
    their helpdesk role assignments.
    """
    try:
        from itcj2.core.models.user_app_role import UserAppRole
        from itcj2.core.models.role_permission import RolePermission
        from itcj2.core.models.permission import Permission
        from itcj2.core.models.app import App

        helpdesk_app = db.query(App).filter_by(key="helpdesk", is_active=True).first()
        warehouse_app = db.query(App).filter_by(key="warehouse", is_active=True).first()

        if not helpdesk_app or not warehouse_app:
            return set()

        rows = (
            db.query(Permission.code)
            .join(RolePermission, RolePermission.perm_id == Permission.id)
            .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
            .filter(
                UserAppRole.user_id == user_id,
                UserAppRole.app_id == helpdesk_app.id,
                Permission.app_id == warehouse_app.id,
            )
            .all()
        )
        return {r[0] for r in rows}
    except Exception:
        logger.warning(
            "Error fetching warehouse perms via helpdesk for user %s", user_id,
            exc_info=True,
        )
        return set()


def require_warehouse_page(perm: str):
    """
    FastAPI page dependency factory for warehouse pages embedded in helpdesk.

    Mirrors the pattern of ``require_page_app`` in ``itcj2/dependencies.py``:
    returns the raw dependency callable (NOT wrapped in ``Depends``).

    - Global admin (JWT role == "admin") bypasses all checks.
    - Otherwise requires the user to have ``perm`` among their effective
      warehouse permissions (derived from their helpdesk role assignments).
    - Raises ``PageLoginRequired`` if not authenticated.
    - Raises ``PageForbidden`` if lacking the permission.

    Usage::

        @router.get("/warehouse/dashboard")
        async def dashboard(
            request: Request,
            user: dict = Depends(require_warehouse_page("warehouse.page.dashboard")),
        ):
            ...
    """

    def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()

        # Global admin bypasses all permission checks
        if user.get("role") == "admin":
            return user

        uid = int(user["sub"])
        warehouse_perms = get_warehouse_perms_via_helpdesk(db, uid)

        if perm not in warehouse_perms:
            raise PageForbidden()

        return user

    return dependency
