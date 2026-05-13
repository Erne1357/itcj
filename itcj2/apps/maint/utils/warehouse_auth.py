"""Warehouse authorization helpers for maint-integrated warehouse pages.

Mirrors ``itcj2/apps/helpdesk/utils/warehouse_auth.py``: maint users hold
warehouse permissions through ``core_role_permissions`` mapped to their
maint roles. The page dependency below performs the cross-app permission
lookup without requiring an explicit ``UserAppRole`` on the warehouse app
(API endpoints under ``/api/warehouse/v2`` still require it — handled by
``database/DML/maint/09_assign_warehouse_user_roles.sql``).
"""
from __future__ import annotations

import logging

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.exceptions import PageForbidden, PageLoginRequired

logger = logging.getLogger(__name__)


def get_warehouse_perms_via_maint(db: Session, user_id: int) -> set[str]:
    """Set of warehouse permission codes the user holds.

    Combina tres fuentes (todas opcionales — la unión es lo que cuenta):

      1. Perms warehouse via UserAppRole en la app MAINT (cross-app):
         el rol del usuario en maint (admin/dispatcher/tech_maint) tiene
         filas en `core_role_permissions` apuntando a permisos warehouse
         (asignados por `database/DML/warehouse/03_assign_warehouse_permissions_to_maint_roles.sql`).
         No requiere UserAppRole en warehouse.

      2. Perms warehouse via PositionAppRole en la app WAREHOUSE:
         el puesto del usuario (ej. `secretary_equipment_maint`) recibe
         rol `dispatcher` en warehouse via
         `database/DML/maint/08_insert_position_app_perm.sql`.

      3. Perms warehouse via PositionAppPerm en la app WAREHOUSE:
         permisos directos al puesto (no usado hoy, futuro).

    El admin global JWT bypassa esta consulta en el dependency wrapper.
    """
    try:
        from itcj2.core.models.user_app_role import UserAppRole
        from itcj2.core.models.role_permission import RolePermission
        from itcj2.core.models.permission import Permission
        from itcj2.core.models.app import App
        from itcj2.core.models.position import UserPosition, PositionAppRole, PositionAppPerm

        maint_app = db.query(App).filter_by(key="maint", is_active=True).first()
        warehouse_app = db.query(App).filter_by(key="warehouse", is_active=True).first()
        if not maint_app or not warehouse_app:
            return set()

        # 1. Cross-app via rol maint
        via_maint = (
            db.query(Permission.code)
            .join(RolePermission, RolePermission.perm_id == Permission.id)
            .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
            .filter(
                UserAppRole.user_id == user_id,
                UserAppRole.app_id == maint_app.id,
                Permission.app_id == warehouse_app.id,
            )
            .all()
        )
        perms = {r[0] for r in via_maint}

        # 2. Via PositionAppRole en warehouse
        via_position_role = (
            db.query(Permission.code)
            .join(RolePermission, RolePermission.perm_id == Permission.id)
            .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
            .join(UserPosition, UserPosition.position_id == PositionAppRole.position_id)
            .filter(
                UserPosition.user_id == user_id,
                UserPosition.is_active == True,
                PositionAppRole.app_id == warehouse_app.id,
                Permission.app_id == warehouse_app.id,
            )
            .all()
        )
        perms |= {r[0] for r in via_position_role}

        # 3. Via PositionAppPerm en warehouse
        via_position_perm = (
            db.query(Permission.code)
            .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
            .join(UserPosition, UserPosition.position_id == PositionAppPerm.position_id)
            .filter(
                UserPosition.user_id == user_id,
                UserPosition.is_active == True,
                PositionAppPerm.app_id == warehouse_app.id,
                PositionAppPerm.allow == True,
            )
            .all()
        )
        perms |= {r[0] for r in via_position_perm}

        return perms
    except Exception:
        logger.warning(
            "Error fetching warehouse perms for user %s",
            user_id,
            exc_info=True,
        )
        return set()


def require_warehouse_page(perm: str):
    """Page dependency factory for warehouse pages embedded in maint.

    - Global admin (JWT role == "admin") bypasses checks.
    - Otherwise requires ``perm`` among effective warehouse perms derived
      from the user's maint role assignments.
    - Raises ``PageLoginRequired`` if unauthenticated.
    - Raises ``PageForbidden`` if missing the permission.
    """

    def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()

        if user.get("role") == "admin":
            return user

        uid = int(user["sub"])
        warehouse_perms = get_warehouse_perms_via_maint(db, uid)

        if perm not in warehouse_perms:
            raise PageForbidden()

        return user

    return dependency
