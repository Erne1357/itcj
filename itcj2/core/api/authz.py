"""
Authorization API v2 — 18 endpoints (apps, roles, permisos, usuarios).
Fuente: itcj/core/routes/api/authz.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-authz"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AppCreateBody(BaseModel):
    key: str
    name: str
    is_active: bool = True
    mobile_enabled: bool = True
    visible_to_students: bool = False
    mobile_url: Optional[str] = None
    mobile_icon: Optional[str] = None


class AppUpdateBody(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    mobile_enabled: Optional[bool] = None
    visible_to_students: Optional[bool] = None
    mobile_url: Optional[str] = None
    mobile_icon: Optional[str] = None


class RoleCreateBody(BaseModel):
    name: str


class PermCreateBody(BaseModel):
    code: str
    name: str
    description: Optional[str] = None


class RolePermsReplaceBody(BaseModel):
    codes: list[str] = []


class UserRoleBody(BaseModel):
    role_name: str


class UserPermBody(BaseModel):
    code: str
    allow: bool = True


# ── Apps ──────────────────────────────────────────────────────────────────────

@router.get("/apps")
def list_apps(
    user: dict = require_perms("itcj", ["core.apps.api.read"]),
    db: DbSession = None,
):
    """Lista todas las aplicaciones registradas."""
    from itcj2.core.models.app import App

    rows = db.query(App).order_by(App.key.asc()).all()
    return {
        "status": "ok",
        "data": [
            {
                "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
                "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
                "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
            }
            for a in rows
        ],
    }


@router.post("/apps", status_code=201)
def create_app(
    body: AppCreateBody,
    user: dict = require_perms("itcj", ["core.apps.api.create"]),
    db: DbSession = None,
):
    """Crea una nueva aplicación."""
    from itcj2.core.models.app import App

    key = body.key.strip()
    name = body.name.strip()
    if not key or not name:
        raise HTTPException(400, detail={"status": "error", "error": "key_and_name_required"})

    if db.query(App).filter_by(key=key).first():
        raise HTTPException(409, detail={"status": "error", "error": "app_key_exists"})

    a = App(
        key=key, name=name, is_active=body.is_active,
        mobile_enabled=body.mobile_enabled, visible_to_students=body.visible_to_students,
        mobile_url=body.mobile_url or None, mobile_icon=body.mobile_icon or None,
    )
    db.add(a)
    db.commit()
    logger.info(f"App '{key}' creada por usuario {int(user['sub'])}")
    return {
        "status": "ok",
        "data": {
            "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
            "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
            "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
        },
    }


@router.patch("/apps/{app_key}")
def update_app(
    app_key: str,
    body: AppUpdateBody,
    user: dict = require_perms("itcj", ["core.apps.api.update"]),
    db: DbSession = None,
):
    """Actualiza una aplicación."""
    from itcj2.core.models.app import App

    a = db.query(App).filter_by(key=app_key).first()
    if not a:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    if body.name is not None:
        a.name = body.name.strip() or a.name
    if body.is_active is not None:
        a.is_active = body.is_active
    if body.mobile_enabled is not None:
        a.mobile_enabled = body.mobile_enabled
    if body.visible_to_students is not None:
        a.visible_to_students = body.visible_to_students
    if body.mobile_url is not None:
        a.mobile_url = body.mobile_url.strip() or None
    if body.mobile_icon is not None:
        a.mobile_icon = body.mobile_icon.strip() or None

    db.commit()
    logger.info(f"App '{app_key}' actualizada por usuario {int(user['sub'])}")
    return {
        "status": "ok",
        "data": {
            "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
            "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
            "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
        },
    }


@router.delete("/apps/{app_key}", status_code=204)
def delete_app(
    app_key: str,
    user: dict = require_perms("itcj", ["core.apps.api.delete"]),
    db: DbSession = None,
):
    """Elimina una aplicación."""
    from itcj2.core.models.app import App

    a = db.query(App).filter_by(key=app_key).first()
    if not a:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    db.delete(a)
    db.commit()
    logger.info(f"App '{app_key}' eliminada por usuario {int(user['sub'])}")


# ── Roles globales ────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(
    user: dict = require_perms("itcj", ["core.roles.api.read"]),
    db: DbSession = None,
):
    """Lista todos los roles globales."""
    from itcj2.core.models.role import Role

    return {
        "status": "ok",
        "data": [
            {"name": r.name}
            for r in db.query(Role).order_by(Role.name.asc()).all()
        ],
    }


@router.post("/roles", status_code=201)
def create_role(
    body: RoleCreateBody,
    user: dict = require_perms("itcj", ["core.roles.api.create"]),
    db: DbSession = None,
):
    """Crea un nuevo rol global."""
    from itcj2.core.models.role import Role

    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail={"status": "error", "error": "name_required"})
    if db.query(Role).filter_by(name=name).first():
        raise HTTPException(409, detail={"status": "error", "error": "role_exists"})

    r = Role(name=name)
    db.add(r)
    db.commit()
    logger.info(f"Rol '{name}' creado por usuario {int(user['sub'])}")
    return {"status": "ok", "data": {"name": r.name}}


@router.delete("/roles/{role_name}", status_code=204)
def delete_role(
    role_name: str,
    user: dict = require_perms("itcj", ["core.roles.api.delete"]),
    db: DbSession = None,
):
    """Elimina un rol global."""
    from itcj2.core.models.role import Role

    r = db.query(Role).filter_by(name=role_name).first()
    if not r:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    db.delete(r)
    db.commit()
    logger.info(f"Rol '{role_name}' eliminado por usuario {int(user['sub'])}")


# ── Permisos por App ──────────────────────────────────────────────────────────

@router.get("/apps/{app_key}/perms")
def list_perms(
    app_key: str,
    user: dict = require_perms("itcj", ["core.permissions.api.read.by_app"]),
    db: DbSession = None,
):
    """Lista permisos de una aplicación."""
    from itcj2.core.services import authz_service as svc

    return {"status": "ok", "data": svc.list_perms(db, app_key)}


@router.post("/apps/{app_key}/perms", status_code=201)
def create_perm(
    app_key: str,
    body: PermCreateBody,
    user: dict = require_perms("itcj", ["core.permissions.api.create"]),
    db: DbSession = None,
):
    """Crea un permiso en una aplicación."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    code = body.code.strip()
    name = body.name.strip()
    if not code or not name:
        raise HTTPException(400, detail={"status": "error", "error": "code_and_name_required"})

    if db.query(Permission).filter_by(app_id=app.id, code=code).first():
        raise HTTPException(409, detail={"status": "error", "error": "permission_exists"})

    perm = Permission(app_id=app.id, code=code, name=name, description=body.description or None)
    db.add(perm)
    db.commit()
    return {"status": "ok", "data": {"code": perm.code, "name": perm.name, "description": perm.description}}


@router.delete("/apps/{app_key}/perms/{code}", status_code=204)
def delete_perm(
    app_key: str,
    code: str,
    user: dict = require_perms("itcj", ["core.permissions.api.delete"]),
    db: DbSession = None,
):
    """Elimina un permiso de una aplicación."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    db.delete(perm)
    db.commit()


# ── Role ⇄ Permission (por App) ───────────────────────────────────────────────

@router.get("/apps/{app_key}/roles/{role_name}/perms")
def get_role_perms(
    app_key: str,
    role_name: str,
    user: dict = require_perms("itcj", ["core.roles.api.read.permissions"]),
    db: DbSession = None,
):
    """Permisos asignados a un rol en una app."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        raise HTTPException(404, detail={"status": "error", "error": "role_not_found"})

    rows = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.app_id == app.id)
        .order_by(Permission.code.asc())
        .all()
    )
    return {"status": "ok", "data": [r[0] for r in rows]}


@router.put("/apps/{app_key}/roles/{role_name}/perms")
def replace_role_perms(
    app_key: str,
    role_name: str,
    body: RolePermsReplaceBody,
    user: dict = require_perms("itcj", ["core.roles.api.assign_permissions"]),
    db: DbSession = None,
):
    """Reemplaza todos los permisos de un rol en una app."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        raise HTTPException(404, detail={"status": "error", "error": "role_not_found"})

    # Eliminar permisos actuales de esta app para el rol
    perm_ids_to_delete = (
        db.query(RolePermission.perm_id)
        .join(Permission, Permission.id == RolePermission.perm_id)
        .filter(RolePermission.role_id == role.id, Permission.app_id == app.id)
        .scalar_subquery()
    )
    db.query(RolePermission).filter(
        RolePermission.role_id == role.id,
        RolePermission.perm_id.in_(perm_ids_to_delete),
    ).delete(synchronize_session=False)

    # Insertar los nuevos
    if body.codes:
        perms = db.query(Permission).filter(
            Permission.app_id == app.id, Permission.code.in_(body.codes)
        ).all()
        db.bulk_save_objects(
            [RolePermission(role_id=role.id, perm_id=p.id) for p in perms]
        )

    db.commit()
    return {"status": "ok", "data": None}


@router.post("/apps/{app_key}/roles/{role_name}/perms/{code}")
def add_role_perm(
    app_key: str,
    role_name: str,
    code: str,
    user: dict = require_perms("itcj", ["core.roles.api.assign_permissions"]),
    db: DbSession = None,
):
    """Agrega un permiso a un rol en una app."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        raise HTTPException(404, detail={"status": "error", "error": "role_not_found"})
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm:
        raise HTTPException(404, detail={"status": "error", "error": "perm_not_found"})

    if not db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first():
        db.add(RolePermission(role_id=role.id, perm_id=perm.id))
        db.commit()
    return {"status": "ok", "data": None}


@router.delete("/apps/{app_key}/roles/{role_name}/perms/{code}", status_code=204)
def remove_role_perm(
    app_key: str,
    role_name: str,
    code: str,
    user: dict = require_perms("itcj", ["core.roles.api.assign_permissions"]),
    db: DbSession = None,
):
    """Remueve un permiso de un rol en una app."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.services import authz_service as svc

    app = svc.get_or_404_app(db, app_key)
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        raise HTTPException(404, detail={"status": "error", "error": "role_not_found"})
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm:
        raise HTTPException(404, detail={"status": "error", "error": "perm_not_found"})

    db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).delete()
    db.commit()


# ── Usuario ⇄ Rol / Permiso por App ──────────────────────────────────────────

@router.get("/apps/{app_key}/users/{user_id}/roles")
def get_user_roles(
    app_key: str,
    user_id: int,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_roles"]),
    db: DbSession = None,
):
    """Roles de un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    return {"status": "ok", "data": sorted(list(svc.user_roles_in_app(db, user_id, app_key)))}


@router.post("/apps/{app_key}/users/{user_id}/roles")
def add_user_role(
    app_key: str,
    user_id: int,
    body: UserRoleBody,
    user: dict = require_perms("itcj", ["core.authz.api.grant_roles"]),
    db: DbSession = None,
):
    """Asigna un rol a un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    role_name = body.role_name.strip()
    if not role_name:
        raise HTTPException(400, detail={"status": "error", "error": "role_name_required"})

    created = svc.grant_role(db, user_id, app_key, role_name)
    return {"status": "ok", "data": {"created": bool(created)}}


@router.delete("/apps/{app_key}/users/{user_id}/roles/{role_name}", status_code=204)
def remove_user_role(
    app_key: str,
    user_id: int,
    role_name: str,
    user: dict = require_perms("itcj", ["core.authz.api.revoke_roles"]),
    db: DbSession = None,
):
    """Revoca un rol de un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    svc.revoke_role(db, user_id, app_key, role_name)


@router.get("/apps/{app_key}/users/{user_id}/perms")
def get_user_perms(
    app_key: str,
    user_id: int,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_permissions"]),
    db: DbSession = None,
):
    """Permisos directos de un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    return {"status": "ok", "data": sorted(list(svc.user_direct_perms_in_app(db, user_id, app_key)))}


@router.post("/apps/{app_key}/users/{user_id}/perms")
def add_user_perm(
    app_key: str,
    user_id: int,
    body: UserPermBody,
    user: dict = require_perms("itcj", ["core.authz.api.grant_permissions"]),
    db: DbSession = None,
):
    """Asigna un permiso directo a un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    code = body.code.strip()
    if not code:
        raise HTTPException(400, detail={"status": "error", "error": "code_required"})

    changed = svc.grant_perm(db, user_id, app_key, code, allow=body.allow)
    return {"status": "ok", "data": {"updated": bool(changed)}}


@router.delete("/apps/{app_key}/users/{user_id}/perms/{code}", status_code=204)
def remove_user_perm(
    app_key: str,
    user_id: int,
    code: str,
    user: dict = require_perms("itcj", ["core.authz.api.revoke_permissions"]),
    db: DbSession = None,
):
    """Revoca un permiso directo de un usuario en una app."""
    from itcj2.core.services import authz_service as svc

    svc.revoke_perm(db, user_id, app_key, code)


@router.get("/apps/{app_key}/users/{user_id}/effective-perms")
def get_user_effective_perms(
    app_key: str,
    user_id: int,
    user: dict = require_perms("itcj", ["core.authz.api.read.user_permissions"]),
    db: DbSession = None,
):
    """Permisos efectivos de un usuario en una app (roles + directos + puestos)."""
    from itcj2.core.services import authz_service as svc

    return {"status": "ok", "data": svc.effective_perms(db, user_id, app_key)}
