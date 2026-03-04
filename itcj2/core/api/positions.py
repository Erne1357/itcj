"""
Positions API v2 — 16 endpoints (CRUD, asignación de usuarios, permisos por puesto).
Fuente: itcj/core/routes/api/positions.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-positions"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class PositionCreateBody(BaseModel):
    code: str
    title: str
    description: Optional[str] = None
    email: Optional[str] = None
    department_id: Optional[int] = None
    allows_multiple: bool = False
    is_active: bool = True


class PositionUpdateBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None
    allows_multiple: Optional[bool] = None
    email: Optional[str] = None


class AssignUserBody(BaseModel):
    user_id: int
    notes: Optional[str] = None
    start_date: Optional[str] = None


class TransferPositionBody(BaseModel):
    new_user_id: int
    old_user_id: Optional[int] = None
    transfer_date: Optional[str] = None


class RemoveUserBody(BaseModel):
    user_id: Optional[int] = None
    end_date: Optional[str] = None


class AssignRoleBody(BaseModel):
    role_name: str


class AssignPermBody(BaseModel):
    code: str
    allow: bool = True


# ── CRUD de Puestos ───────────────────────────────────────────────────────────

@router.get("")
def list_positions(
    department: Optional[str] = None,
    user: dict = require_perms("itcj", ["core.positions.api.read"]),
    db: DbSession = None,
):
    """Lista todos los puestos organizacionales."""
    from itcj2.core.services import positions_service as svc

    positions = svc.list_positions(db, department)
    return {
        "status": "ok",
        "data": [
            {
                "id": p.id,
                "code": p.code,
                "title": p.title,
                "description": p.description,
                "email": p.email,
                "department_id": p.department_id,
                "is_active": p.is_active,
                "allows_multiple": p.allows_multiple,
                "current_user": svc.get_position_current_user(db, p.id),
            }
            for p in positions
        ],
    }


@router.get("/users/{user_id}/positions")
def get_user_positions(
    user_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.read.assignments"]),
    db: DbSession = None,
):
    """Puestos activos de un usuario."""
    from itcj2.core.services import positions_service as svc

    return {"status": "ok", "data": svc.get_user_active_positions(db, user_id)}


@router.get("/users/{user_id}/apps/{app_key}/position-perms")
def get_user_position_permissions(
    user_id: int,
    app_key: str,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_permissions"]),
    db: DbSession = None,
):
    """Permisos efectivos de un usuario vía sus puestos en una app."""
    from itcj2.core.services import positions_service as svc

    try:
        perms = svc.get_position_effective_permissions(db, user_id, app_key)
        return {"status": "ok", "data": sorted(list(perms))}
    except Exception as e:
        raise HTTPException(400, detail={"status": "error", "error": str(e)})


@router.get("/{position_id}")
def get_position(
    position_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.read"]),
    db: DbSession = None,
):
    """Detalle completo de un puesto con usuarios y asignaciones de apps."""
    from itcj2.core.services import positions_service as svc

    position = svc.get_position_by_id(db, position_id)
    if not position:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    return {
        "status": "ok",
        "data": {
            "id": position.id,
            "code": position.code,
            "title": position.title,
            "description": position.description,
            "email": position.email,
            "department_id": position.department_id,
            "is_active": position.is_active,
            "allows_multiple": position.allows_multiple,
            "current_users": svc.get_position_current_users(db, position_id),
            "assignments": svc.get_position_assignments(db, position_id),
        },
    }


@router.post("", status_code=201)
def create_position(
    body: PositionCreateBody,
    user: dict = require_perms("itcj", ["core.positions.api.create"]),
    db: DbSession = None,
):
    """Crea un nuevo puesto organizacional."""
    from itcj2.core.services import positions_service as svc

    code = body.code.strip()
    title = body.title.strip()
    if not code or not title:
        raise HTTPException(400, detail={"status": "error", "error": "code_and_title_required"})

    try:
        position = svc.create_position(
            db,
            code=code,
            title=title,
            description=body.description.strip() if body.description else None,
            email=body.email.strip() if body.email else None,
            department_id=body.department_id,
            allows_multiple=body.allows_multiple,
            is_active=body.is_active,
        )
        logger.info(f"Puesto '{title}' creado por usuario {int(user['sub'])}")
        return {
            "status": "ok",
            "data": {
                "id": position.id, "code": position.code, "title": position.title,
                "description": position.description, "email": position.email,
                "department_id": position.department_id, "is_active": position.is_active,
                "allows_multiple": position.allows_multiple,
            },
        }
    except ValueError as e:
        raise HTTPException(409, detail={"status": "error", "error": str(e)})


@router.patch("/{position_id}")
def update_position(
    position_id: int,
    body: PositionUpdateBody,
    user: dict = require_perms("itcj", ["core.positions.api.update"]),
    db: DbSession = None,
):
    """Actualiza un puesto organizacional."""
    from itcj2.core.services import positions_service as svc

    updates = body.model_dump(exclude_none=True)
    try:
        position = svc.update_position(db, position_id, **updates)
        logger.info(f"Puesto {position_id} actualizado por usuario {int(user['sub'])}")
        return {
            "status": "ok",
            "data": {
                "id": position.id, "code": position.code, "title": position.title,
                "description": position.description, "email": position.email,
                "department_id": position.department_id, "allows_multiple": position.allows_multiple,
                "is_active": position.is_active,
                "department": {
                    "id": position.department.id,
                    "name": position.department.name,
                    "code": position.department.code,
                } if position.department else None,
            },
        }
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})


@router.delete("/{position_id}", status_code=204)
def delete_position(
    position_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.delete"]),
    db: DbSession = None,
):
    """Elimina un puesto (solo si no tiene usuarios activos)."""
    from itcj2.core.models.position import UserPosition
    from itcj2.core.services import positions_service as svc

    active = db.query(UserPosition).filter_by(position_id=position_id, is_active=True).count()
    if active > 0:
        raise HTTPException(409, detail={"status": "error", "error": "position_has_active_users"})

    position = svc.get_position_by_id(db, position_id)
    if not position:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    svc.delete_position(db, position_id)
    logger.info(f"Puesto {position_id} eliminado por usuario {int(user['sub'])}")


# ── Asignación de Usuarios ────────────────────────────────────────────────────

@router.get("/{position_id}/user")
def get_position_current_user(
    position_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.read.assignments"]),
    db: DbSession = None,
):
    """Usuario actualmente asignado al puesto."""
    from itcj2.core.services import positions_service as svc

    return {"status": "ok", "data": svc.get_position_current_user(db, position_id)}


@router.get("/{position_id}/users")
def get_position_all_users(
    position_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.read.assignments"]),
    db: DbSession = None,
):
    """Todos los usuarios asignados al puesto."""
    from itcj2.core.services import positions_service as svc

    return {"status": "ok", "data": svc.get_position_current_users(db, position_id)}


@router.post("/{position_id}/assign-user", status_code=201)
def assign_user_to_position(
    position_id: int,
    body: AssignUserBody,
    user: dict = require_perms("itcj", ["core.positions.api.assign_users"]),
    db: DbSession = None,
):
    """Asigna un usuario a un puesto."""
    from itcj2.core.services import positions_service as svc

    start_date = None
    if body.start_date:
        try:
            start_date = datetime.strptime(body.start_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, detail={"status": "error", "error": "invalid_date_format"})

    try:
        assignment = svc.assign_user_to_position(db, body.user_id, position_id, start_date, body.notes)
        logger.info(f"Usuario {body.user_id} asignado al puesto {position_id}")
        return {
            "status": "ok",
            "data": {
                "user_id": assignment.user_id,
                "position_id": assignment.position_id,
                "start_date": assignment.start_date.isoformat(),
                "notes": assignment.notes,
            },
        }
    except ValueError as e:
        raise HTTPException(409, detail={"status": "error", "error": str(e)})


@router.post("/{position_id}/transfer")
def transfer_position(
    position_id: int,
    body: TransferPositionBody,
    user: dict = require_perms("itcj", ["core.positions.api.assign_users"]),
    db: DbSession = None,
):
    """Transfiere un puesto de un usuario a otro."""
    from itcj2.core.services import positions_service as svc

    transfer_date = None
    if body.transfer_date:
        try:
            transfer_date = datetime.strptime(body.transfer_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, detail={"status": "error", "error": "invalid_date_format"})

    old_user_id = body.old_user_id
    if not old_user_id:
        current = svc.get_position_current_user(db, position_id)
        if not current:
            raise HTTPException(400, detail={"status": "error", "error": "no_current_user"})
        old_user_id = current["user_id"]

    try:
        svc.transfer_position(db, old_user_id, body.new_user_id, position_id, transfer_date)
        return {"status": "ok", "data": {"transferred": True}}
    except Exception as e:
        raise HTTPException(500, detail={"status": "error", "error": str(e)})


@router.delete("/{position_id}/remove-user")
def remove_user_from_position(
    position_id: int,
    body: RemoveUserBody,
    user: dict = require_perms("itcj", ["core.positions.api.unassign_users"]),
    db: DbSession = None,
):
    """Remueve un usuario de un puesto."""
    from itcj2.core.services import positions_service as svc

    end_date = None
    if body.end_date:
        try:
            end_date = datetime.strptime(body.end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, detail={"status": "error", "error": "invalid_date_format"})

    user_id = body.user_id
    if not user_id:
        current = svc.get_position_current_user(db, position_id)
        if not current:
            raise HTTPException(400, detail={"status": "error", "error": "no_current_user"})
        user_id = current["user_id"]

    success = svc.remove_user_from_position(db, user_id, position_id, end_date)
    if success:
        return {"status": "ok", "data": {"removed": True}}
    raise HTTPException(404, detail={"status": "error", "error": "removal_failed"})


# ── Permisos por Puesto (App assignments) ─────────────────────────────────────

@router.get("/{position_id}/assignments")
def get_position_assignments(
    position_id: int,
    user: dict = require_perms("itcj", ["core.positions.api.read.assignments"]),
    db: DbSession = None,
):
    """Asignaciones de apps (roles y permisos) del puesto."""
    from itcj2.core.services import positions_service as svc

    try:
        return {"status": "ok", "data": svc.get_position_assignments(db, position_id)}
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})


@router.get("/{position_id}/apps/{app_key}/roles")
def get_position_app_roles(
    position_id: int,
    app_key: str,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_roles"]),
    db: DbSession = None,
):
    """Roles asignados a un puesto en una app."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.position import PositionAppRole
    from itcj2.core.services.authz_service import get_or_404_app

    app = get_or_404_app(db, app_key)
    roles = (
        db.query(Role.name)
        .join(PositionAppRole, PositionAppRole.role_id == Role.id)
        .filter(PositionAppRole.position_id == position_id, PositionAppRole.app_id == app.id)
        .all()
    )
    return {"status": "ok", "data": [r[0] for r in roles]}


@router.post("/{position_id}/apps/{app_key}/roles")
def assign_role_to_position(
    position_id: int,
    app_key: str,
    body: AssignRoleBody,
    user: dict = require_perms("itcj", ["core.authz.api.grant_roles"]),
    db: DbSession = None,
):
    """Asigna un rol a un puesto en una app."""
    from itcj2.core.services import positions_service as svc

    role_name = body.role_name.strip()
    if not role_name:
        raise HTTPException(400, detail={"status": "error", "error": "role_name_required"})

    try:
        created = svc.assign_role_to_position(db, position_id, app_key, role_name)
        return {"status": "ok", "data": {"created": created}}
    except ValueError as e:
        raise HTTPException(400, detail={"status": "error", "error": str(e)})


@router.delete("/{position_id}/apps/{app_key}/roles/{role_name}", status_code=204)
def remove_role_from_position(
    position_id: int,
    app_key: str,
    role_name: str,
    user: dict = require_perms("itcj", ["core.authz.api.revoke_roles"]),
    db: DbSession = None,
):
    """Remueve un rol de un puesto en una app."""
    from itcj2.core.services import positions_service as svc

    svc.remove_role_from_position(db, position_id, app_key, role_name)


@router.get("/{position_id}/apps/{app_key}/perms")
def get_position_app_perms(
    position_id: int,
    app_key: str,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_permissions"]),
    db: DbSession = None,
):
    """Permisos directos asignados a un puesto en una app."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.position import PositionAppPerm
    from itcj2.core.services.authz_service import get_or_404_app

    app = get_or_404_app(db, app_key)
    perms = (
        db.query(Permission.code)
        .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
        .filter(
            PositionAppPerm.position_id == position_id,
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
        )
        .all()
    )
    return {"status": "ok", "data": [p[0] for p in perms]}


@router.post("/{position_id}/apps/{app_key}/perms")
def assign_perm_to_position(
    position_id: int,
    app_key: str,
    body: AssignPermBody,
    user: dict = require_perms("itcj", ["core.authz.api.grant_permissions"]),
    db: DbSession = None,
):
    """Asigna un permiso directo a un puesto en una app."""
    from itcj2.core.services import positions_service as svc

    perm_code = body.code.strip()
    if not perm_code:
        raise HTTPException(400, detail={"status": "error", "error": "code_required"})

    try:
        created = svc.assign_permission_to_position(db, position_id, app_key, perm_code, body.allow)
        return {"status": "ok", "data": {"updated": created}}
    except ValueError as e:
        raise HTTPException(400, detail={"status": "error", "error": str(e)})


@router.delete("/{position_id}/apps/{app_key}/perms/{perm_code}", status_code=204)
def remove_perm_from_position(
    position_id: int,
    app_key: str,
    perm_code: str,
    user: dict = require_perms("itcj", ["core.authz.api.revoke_permissions"]),
    db: DbSession = None,
):
    """Remueve un permiso de un puesto en una app."""
    from itcj2.core.models.position import PositionAppPerm
    from itcj2.core.services.authz_service import get_or_404_app, get_perm

    app = get_or_404_app(db, app_key)
    perm = get_perm(db, app.id, perm_code)
    if not perm:
        raise HTTPException(404, detail={"status": "error", "error": "permission_not_found"})

    db.query(PositionAppPerm).filter_by(
        position_id=position_id, app_id=app.id, perm_id=perm.id
    ).delete()
    db.commit()


@router.get("/{position_id}/effective-perms/{app_key}")
def get_position_effective_perms(
    position_id: int,
    app_key: str,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_permissions"]),
    db: DbSession = None,
):
    """Permisos efectivos de un puesto en una app (roles + permisos directos)."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.models.position import PositionAppRole, PositionAppPerm
    from itcj2.core.services.authz_service import get_or_404_app

    app = get_or_404_app(db, app_key)

    perms_via_roles = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
        .filter(
            PositionAppRole.position_id == position_id,
            PositionAppRole.app_id == app.id,
            Permission.app_id == app.id,
        )
        .all()
    )

    direct_perms = (
        db.query(Permission.code)
        .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
        .filter(
            PositionAppPerm.position_id == position_id,
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
            Permission.app_id == app.id,
        )
        .all()
    )

    all_perms: set[str] = set()
    all_perms.update(p[0] for p in perms_via_roles)
    all_perms.update(p[0] for p in direct_perms)

    return {"status": "ok", "data": sorted(all_perms)}
