"""
Users Admin API v2 — gestión de usuarios (lista, crear, actualizar, reset).
Fuente: itcj/core/routes/api/users.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, case

from itcj2.dependencies import DbSession, CurrentUser, require_perms, require_roles

router = APIRouter(prefix="/users", tags=["users-admin"])
logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "tecno#2K"


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateUserBody(BaseModel):
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    email: Optional[str] = None
    user_type: str  # "student" | "staff"
    control_number: Optional[str] = None
    username: Optional[str] = None
    password: str


class UpdateUserBody(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    control_number: Optional[str] = None


# ── List users ────────────────────────────────────────────────────────────────

@router.get("")
def list_users(
    search: str = Query("", description="Búsqueda por nombre, email, username o no. control"),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="'active' o 'inactive'"),
    only_staff: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: dict = require_perms("itcj", ["core.users.api.read"]),
    db: DbSession = None,
):
    """Lista usuarios con filtros y paginación."""
    from itcj2.core.models.user import User
    from itcj2.core.models.role import Role
    from itcj2.models.base import paginate

    query = db.query(User)

    if status == "active":
        query = query.filter(User.is_active == True)  # noqa: E712
    elif status == "inactive":
        query = query.filter(User.is_active == False)  # noqa: E712

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.username.ilike(pattern),
                User.control_number.ilike(pattern),
            )
        )

    if only_staff:
        query = query.filter(User.control_number == None)  # noqa: E711

    if role:
        query = query.join(Role, User.role_id == Role.id).filter(Role.name == role)

    query = query.order_by(User.full_name)

    p = paginate(query, page=page, per_page=per_page)

    users_data = [
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "username": u.username,
            "control_number": u.control_number,
            "role": u.role.name if u.role else None,
            "roles": [u.role.name] if u.role else [],
            "is_active": u.is_active,
        }
        for u in p.items
    ]

    return {
        "status": "ok",
        "data": {
            "users": users_data,
            "pagination": {
                "page": p.page,
                "per_page": p.per_page,
                "total": p.total,
                "pages": p.pages,
                "has_next": p.has_next,
                "has_prev": p.has_prev,
                "next_num": p.next_num,
                "prev_num": p.prev_num,
            },
        },
    }


# ── Create user ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_user(
    body: CreateUserBody,
    user: dict = require_perms("itcj", ["core.users.api.create"]),
    db: DbSession = None,
):
    """Crea un nuevo usuario (estudiante o personal)."""
    from itcj2.core.models.user import User
    from itcj2.core.models.role import Role
    from itcj2.core.utils.security import hash_nip
    from sqlalchemy.exc import IntegrityError

    # Resolver first/last/middle desde full_name si es necesario
    first_name = (body.first_name or "").strip() or None
    last_name = (body.last_name or "").strip() or None
    middle_name = (body.middle_name or "").strip() or None

    if not (first_name and last_name) and body.full_name:
        parts = body.full_name.strip().split()
        if len(parts) < 2:
            raise HTTPException(400, detail={"status": "error", "error": "invalid_name_format"})
        if len(parts) >= 3:
            first_name = " ".join(parts[:-2]).upper()
            last_name = parts[-2].upper()
            middle_name = parts[-1].upper()
        else:
            first_name = parts[0].upper()
            last_name = parts[-1].upper()
            middle_name = None

    if not (first_name and last_name):
        raise HTTPException(400, detail={"status": "error", "error": "name_required"})

    user_type = body.user_type
    if user_type == "student":
        role_name = "student"
        ctrl = (body.control_number or "").strip()
        if not ctrl or len(ctrl) != 8:
            raise HTTPException(400, detail={"status": "error", "error": "valid_control_number_required"})
        if db.query(User).filter_by(control_number=ctrl).first():
            raise HTTPException(409, detail={"status": "error", "error": "control_number_already_exists"})
    elif user_type == "staff":
        role_name = "staff"
        uname = (body.username or "").strip()
        if not uname:
            raise HTTPException(400, detail={"status": "error", "error": "username_required_for_staff"})
        if db.query(User).filter_by(username=uname).first():
            raise HTTPException(409, detail={"status": "error", "error": "username_already_exists"})
    else:
        raise HTTPException(400, detail={"status": "error", "error": "invalid_user_type"})

    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        raise HTTPException(500, detail={"status": "error", "error": f"default_role_{role_name}_not_found"})

    try:
        new_user = User(
            first_name=first_name.upper(),
            last_name=last_name.upper(),
            middle_name=middle_name.upper() if middle_name else None,
            email=(body.email or "").strip() or None,
            role_id=role.id,
            password_hash=hash_nip(body.password),
            control_number=(body.control_number or "").strip() or None if user_type == "student" else None,
            username=(body.username or "").strip() or None if user_type == "staff" else None,
            must_change_password=(user_type == "staff"),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(f"Usuario '{new_user.full_name}' creado por {int(user['sub'])}")
        return {
            "status": "ok",
            "data": {
                "id": new_user.id,
                "full_name": new_user.full_name,
                "email": new_user.email,
                "username": new_user.username,
                "control_number": new_user.control_number,
                "is_active": new_user.is_active,
            },
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"status": "error", "error": "duplicate_value"})


# ── Current user department ───────────────────────────────────────────────────

@router.get("/me/department")
def get_my_department(
    user: CurrentUser,
    db: DbSession = None,
):
    """Departamento del usuario actual."""
    from itcj2.core.services.departments_service import get_user_department

    dept = get_user_department(db, int(user["sub"]))
    if not dept:
        raise HTTPException(404, detail={"status": "error", "error": "no_department"})
    return {"success": True, "data": {"id": dept.id, "name": dept.name, "code": dept.code}}


# ── Specific user department ──────────────────────────────────────────────────

@router.get("/{target_user_id}/department")
def get_user_department_by_id(
    target_user_id: int,
    user: CurrentUser,
    db: DbSession = None,
):
    """Departamento de un usuario específico (requiere acceso a helpdesk)."""
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.core.services.authz_service import user_roles_in_app

    current_user_id = int(user["sub"])
    roles = user_roles_in_app(db, current_user_id, "helpdesk")
    allowed_roles = {"admin", "tech_desarrollo", "tech_soporte"}
    if not (roles & allowed_roles):
        raise HTTPException(403, detail={"success": False, "error": "forbidden"})

    dept = get_user_department(db, target_user_id)
    if not dept:
        raise HTTPException(404, detail={"success": False, "error": "no_department"})
    return {"success": True, "data": {"id": dept.id, "name": dept.name, "code": dept.code}}


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    current_user: dict = require_perms("itcj", ["core.users.api.reset_password"]),
    db: DbSession = None,
):
    """Resetea la contraseña de un usuario a la contraseña por defecto."""
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(404, detail={"status": "error", "error": "user_not_found"})

    if u.control_number:
        raise HTTPException(400, detail={"status": "error", "error": "cannot_reset_student_password"})

    u.password_hash = hash_nip(DEFAULT_PASSWORD)
    u.must_change_password = True
    db.commit()

    logger.info(f"Contraseña reseteada para usuario {user_id} por {int(current_user['sub'])}")
    return {"status": "ok", "data": {"user_id": u.id, "must_change_password": True}}


# ── Toggle status ─────────────────────────────────────────────────────────────

@router.post("/{user_id}/toggle-status")
def toggle_user_status(
    user_id: int,
    current_user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Activa o desactiva la cuenta de un usuario."""
    from itcj2.core.models.user import User

    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(404, detail={"status": "error", "error": "user_not_found"})

    if int(current_user["sub"]) == u.id:
        raise HTTPException(400, detail={"status": "error", "error": "cannot_toggle_own_account"})

    u.is_active = not u.is_active
    db.commit()

    action = "activada" if u.is_active else "desactivada"
    logger.info(f"Cuenta de usuario {user_id} {action} por {int(current_user['sub'])}")
    return {"status": "ok", "data": {"user_id": u.id, "is_active": u.is_active, "message": f"Cuenta {action}"}}


# ── Update user ───────────────────────────────────────────────────────────────

@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserBody,
    current_user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Actualiza la información de un usuario."""
    from itcj2.core.models.user import User
    from sqlalchemy.exc import IntegrityError

    u = db.query(User).get(user_id)
    if not u:
        raise HTTPException(404, detail={"status": "error", "error": "user_not_found"})

    if body.first_name is not None:
        val = body.first_name.strip()
        if not val:
            raise HTTPException(400, detail={"status": "error", "error": "first_name_required"})
        u.first_name = val

    if body.last_name is not None:
        val = body.last_name.strip()
        if not val:
            raise HTTPException(400, detail={"status": "error", "error": "last_name_required"})
        u.last_name = val

    if body.middle_name is not None:
        u.middle_name = body.middle_name.strip() or None

    if body.email is not None:
        u.email = body.email.strip() or None

    if body.username is not None and not u.control_number:
        val = body.username.strip()
        if not val:
            raise HTTPException(400, detail={"status": "error", "error": "username_required"})
        existing = db.query(User).filter(User.username == val, User.id != user_id).first()
        if existing:
            raise HTTPException(409, detail={"status": "error", "error": "username_already_exists"})
        u.username = val

    if body.control_number is not None and u.control_number is not None:
        val = body.control_number.strip()
        if not val or len(val) != 8 or not val.isdigit():
            raise HTTPException(400, detail={"status": "error", "error": "invalid_control_number"})
        existing = db.query(User).filter(User.control_number == val, User.id != user_id).first()
        if existing:
            raise HTTPException(409, detail={"status": "error", "error": "control_number_already_exists"})
        u.control_number = val

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"status": "error", "error": "duplicate_value"})

    logger.info(f"Usuario {user_id} actualizado por {int(current_user['sub'])}")
    return {"status": "ok", "data": u.to_dict()}


# ── Users by app ──────────────────────────────────────────────────────────────

@router.get("/by-app/{app_key}")
def list_users_by_app(
    app_key: str,
    search: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    user: CurrentUser = None,
    db: DbSession = None,
):
    """Lista usuarios con acceso a una aplicación específica."""
    from itcj2.core.models.app import App
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.user_app_perm import UserAppPerm
    from itcj2.core.models.position import UserPosition, PositionAppRole, PositionAppPerm
    from itcj2.core.services.authz_service import user_roles_in_app, has_any_assignment
    from itcj2.models.base import paginate

    # Requiere acceso a helpdesk (cualquier rol/permiso)
    if user.get("role") != "admin" and not has_any_assignment(db, int(user["sub"]), "helpdesk", include_positions=True):
        raise HTTPException(403, detail={"status": "error", "error": "forbidden"})

    app = db.query(App).filter_by(key=app_key, is_active=True).first()
    if not app:
        raise HTTPException(404, detail={"status": "error", "error": "app_not_found"})

    users_with_roles = db.query(User.id).join(
        UserAppRole, UserAppRole.user_id == User.id
    ).filter(UserAppRole.app_id == app.id, User.is_active == True)  # noqa: E712

    users_with_perms = db.query(User.id).join(
        UserAppPerm, UserAppPerm.user_id == User.id
    ).filter(UserAppPerm.app_id == app.id, UserAppPerm.allow == True, User.is_active == True)  # noqa: E712

    users_with_pos_roles = db.query(User.id).join(
        UserPosition, UserPosition.user_id == User.id
    ).join(
        PositionAppRole, PositionAppRole.position_id == UserPosition.position_id
    ).filter(PositionAppRole.app_id == app.id, UserPosition.is_active == True, User.is_active == True)  # noqa: E712

    users_with_pos_perms = db.query(User.id).join(
        UserPosition, UserPosition.user_id == User.id
    ).join(
        PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id
    ).filter(
        PositionAppPerm.app_id == app.id,
        PositionAppPerm.allow == True,  # noqa: E712
        UserPosition.is_active == True,  # noqa: E712
        User.is_active == True,  # noqa: E712
    )

    user_ids = (
        users_with_roles.union(users_with_perms)
        .union(users_with_pos_roles)
        .union(users_with_pos_perms)
    )

    query = db.query(User).filter(User.id.in_(user_ids), User.is_active == True)  # noqa: E712

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.username.ilike(pattern),
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.control_number.ilike(pattern),
            )
        ).order_by(
            case((User.username.ilike(pattern), 0), else_=1),
            User.full_name,
        )
    else:
        query = query.order_by(User.full_name)

    p = paginate(query, page=page, per_page=per_page)

    users_data = []
    for u in p.items:
        roles = user_roles_in_app(db, u.id, app_key)
        users_data.append({
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "username": u.username,
            "control_number": u.control_number,
            "roles": list(roles) if isinstance(roles, set) else roles,
            "is_active": u.is_active,
        })

    return {
        "status": "ok",
        "data": {
            "users": users_data,
            "pagination": {
                "page": p.page,
                "per_page": p.per_page,
                "total": p.total,
                "pages": p.pages,
                "has_next": p.has_next,
                "has_prev": p.has_prev,
                "next_num": p.next_num,
                "prev_num": p.prev_num,
            },
        },
    }
