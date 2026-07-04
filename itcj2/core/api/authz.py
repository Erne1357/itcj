"""
Authorization API v2 — 18 endpoints (apps, roles, permisos, usuarios).
Fuente: itcj/core/routes/api/authz.py
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-authz"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_hex_color(v: Optional[str]) -> Optional[str]:
    """None → no enviado; "" → limpiar (sentinel para update); si no, #RRGGBB."""
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return ""
    if not _HEX_COLOR_RE.match(v):
        raise ValueError("color debe ser hex #RRGGBB")
    return v


class AppCreateBody(BaseModel):
    key: str
    name: str
    is_active: bool = True
    mobile_enabled: bool = True
    visible_to_students: bool = False
    mobile_url: Optional[str] = None
    mobile_icon: Optional[str] = None
    color: Optional[str] = None        # "#RRGGBB"
    icon_class: Optional[str] = None   # p.ej. "bi-headset"

    @field_validator("color")
    @classmethod
    def _color_hex(cls, v):
        return _validate_hex_color(v)


class AppUpdateBody(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    mobile_enabled: Optional[bool] = None
    visible_to_students: Optional[bool] = None
    mobile_url: Optional[str] = None
    mobile_icon: Optional[str] = None
    color: Optional[str] = None        # "#RRGGBB"; "" limpia
    icon_class: Optional[str] = None   # "" limpia

    @field_validator("color")
    @classmethod
    def _color_hex(cls, v):
        return _validate_hex_color(v)


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
        "success": True,
        "data": [
            {
                "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
                "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
                "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
                "color": a.color, "icon_class": a.icon_class,
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
        raise HTTPException(400, detail="La clave y el nombre son requeridos")

    if db.query(App).filter_by(key=key).first():
        raise HTTPException(409, detail="Ya existe una aplicación con esa clave")

    a = App(
        key=key, name=name, is_active=body.is_active,
        mobile_enabled=body.mobile_enabled, visible_to_students=body.visible_to_students,
        mobile_url=body.mobile_url or None, mobile_icon=body.mobile_icon or None,
        color=body.color or None, icon_class=(body.icon_class or "").strip() or None,
    )
    db.add(a)
    db.commit()
    from itcj2.core.services.app_style_cache import invalidate_app_styles
    invalidate_app_styles()
    logger.info(f"App '{key}' creada por usuario {int(user['sub'])}")
    return {
        "success": True,
        "data": {
            "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
            "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
            "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
            "color": a.color, "icon_class": a.icon_class,
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
        raise HTTPException(404, detail="Aplicación no encontrada")

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
    if body.color is not None:
        a.color = body.color or None  # "" (ya validado) limpia el color
    if body.icon_class is not None:
        a.icon_class = body.icon_class.strip() or None

    db.commit()
    from itcj2.core.services.app_style_cache import invalidate_app_styles
    invalidate_app_styles()
    logger.info(f"App '{app_key}' actualizada por usuario {int(user['sub'])}")
    return {
        "success": True,
        "data": {
            "id": a.id, "key": a.key, "name": a.name, "is_active": a.is_active,
            "mobile_enabled": a.mobile_enabled, "visible_to_students": a.visible_to_students,
            "mobile_url": a.mobile_url, "mobile_icon": a.mobile_icon,
            "color": a.color, "icon_class": a.icon_class,
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
        raise HTTPException(404, detail="Aplicación no encontrada")

    db.delete(a)
    db.commit()
    from itcj2.core.services.authz_cache import invalidate_all
    invalidate_all()  # el cascade quita grants; sin esto el caché sirve stale hasta TTL
    from itcj2.core.services.app_style_cache import invalidate_app_styles
    invalidate_app_styles()
    logger.info(f"App '{app_key}' eliminada por usuario {int(user['sub'])}")


# ── Roles globales ────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(
    user: dict = require_perms("itcj", ["core.roles.api.read"]),
    db: DbSession = None,
):
    """Lista todos los roles globales con conteo de usuarios (sin N+1)."""
    from sqlalchemy import func

    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User

    counts = dict(
        db.query(User.role_id, func.count(User.id))
        .filter(User.role_id.isnot(None))
        .group_by(User.role_id)
        .all()
    )
    return {
        "success": True,
        "data": [
            {"id": r.id, "name": r.name, "users_count": counts.get(r.id, 0)}
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
        raise HTTPException(400, detail="El nombre es requerido")
    if db.query(Role).filter_by(name=name).first():
        raise HTTPException(409, detail="Ya existe un rol con ese nombre")

    r = Role(name=name)
    db.add(r)
    db.commit()
    logger.info(f"Rol '{name}' creado por usuario {int(user['sub'])}")
    return {"success": True, "data": {"name": r.name}}


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
        raise HTTPException(404, detail="Rol no encontrado")

    db.delete(r)
    db.commit()
    from itcj2.core.services.authz_cache import invalidate_all
    invalidate_all()  # el cascade quita grants del rol; evita servir stale hasta TTL
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

    return {"success": True, "data": svc.list_perms(db, app_key)}


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
        raise HTTPException(400, detail="El código y el nombre son requeridos")

    if db.query(Permission).filter_by(app_id=app.id, code=code).first():
        raise HTTPException(409, detail="Ya existe un permiso con ese código en la aplicación")

    perm = Permission(app_id=app.id, code=code, name=name, description=body.description or None)
    db.add(perm)
    db.commit()
    return {"success": True, "data": {"code": perm.code, "name": perm.name, "description": perm.description}}


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
        raise HTTPException(404, detail="Permiso no encontrado")

    db.delete(perm)
    db.commit()
    from itcj2.core.services.authz_cache import invalidate_all
    invalidate_all()  # el cascade quita el perm de roles/usuarios/puestos


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
        raise HTTPException(404, detail="Rol no encontrado")

    rows = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.app_id == app.id)
        .order_by(Permission.code.asc())
        .all()
    )
    return {"success": True, "data": [r[0] for r in rows]}


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
        raise HTTPException(404, detail="Rol no encontrado")

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
    from itcj2.core.services.authz_cache import invalidate_all
    invalidate_all()  # role-wide: afecta a todos los usuarios con este rol
    return {"success": True, "data": None}


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
        raise HTTPException(404, detail="Rol no encontrado")
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm:
        raise HTTPException(404, detail="Permiso no encontrado")

    if not db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first():
        db.add(RolePermission(role_id=role.id, perm_id=perm.id))
        db.commit()
        from itcj2.core.services.authz_cache import invalidate_all
        invalidate_all()  # role-wide
    return {"success": True, "data": None}


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
        raise HTTPException(404, detail="Rol no encontrado")
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm:
        raise HTTPException(404, detail="Permiso no encontrado")

    db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).delete()
    db.commit()
    from itcj2.core.services.authz_cache import invalidate_all
    invalidate_all()  # role-wide


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

    return {"success": True, "data": sorted(list(svc.user_roles_in_app(db, user_id, app_key)))}


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
        raise HTTPException(400, detail="El nombre del rol es requerido")

    created = svc.grant_role(db, user_id, app_key, role_name)
    return {"success": True, "data": {"created": bool(created)}}


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

    return {"success": True, "data": sorted(list(svc.user_direct_perms_in_app(db, user_id, app_key)))}


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
        raise HTTPException(400, detail="El código del permiso es requerido")

    changed = svc.grant_perm(db, user_id, app_key, code, allow=body.allow)
    resp = {"success": True, "data": {"updated": bool(changed)}}

    # Guardrail: un perm de scope departamental (.subtree) sin puesto que lo respalde
    # no tiene ancla → no surte efecto (fail-closed). Avisamos para no dejar un
    # permiso muerto silencioso. Ver spec org-scoped-authz §3.6.
    if body.allow and code.endswith(".subtree"):
        from itcj2.core.services.scope_service import granting_departments
        if not granting_departments(db, user_id, app_key, code):
            resp["warning"] = "scope_departamental_sin_puesto"

    return resp


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

    return {"success": True, "data": svc.effective_perms(db, user_id, app_key)}
