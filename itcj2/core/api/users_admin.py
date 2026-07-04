"""
Users Admin API v2 — gestión de usuarios (lista, crear, actualizar, reset).
Fuente: itcj/core/routes/api/users.py
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, case

from itcj2.dependencies import DbSession, CurrentUser, require_perms, require_roles

router = APIRouter(prefix="/users", tags=["users-admin"])
logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "tecno#2K"

# D8/C7 (core-config-revamp): 8 dígitos (licenciatura) o letra + 7-9 dígitos
# (posgrado). MISMO regex que el pattern del front (users.html #controlNumber).
# Un numérico de 9 dígitos NO es válido.
CONTROL_NUMBER_RE = re.compile(r"^(\d{8}|[A-Za-z]\d{7,9})$")


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _app_access_user_ids(db, app_id: int):
    """Query de ids de usuario con CUALQUIER asignación en la app:
    rol directo, permiso directo, o rol/permiso vía puesto activo.
    (Los filtros de is_active de usuario se aplican en el query exterior.)
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.user_app_perm import UserAppPerm
    from itcj2.core.models.position import UserPosition, PositionAppRole, PositionAppPerm
    from itcj2.core.services.authz_service import _active_position_filter

    with_roles = db.query(User.id).join(
        UserAppRole, UserAppRole.user_id == User.id
    ).filter(UserAppRole.app_id == app_id)

    with_perms = db.query(User.id).join(
        UserAppPerm, UserAppPerm.user_id == User.id
    ).filter(UserAppPerm.app_id == app_id, UserAppPerm.allow == True)  # noqa: E712

    with_pos_roles = db.query(User.id).join(
        UserPosition, UserPosition.user_id == User.id
    ).join(
        PositionAppRole, PositionAppRole.position_id == UserPosition.position_id
    ).filter(PositionAppRole.app_id == app_id, _active_position_filter())

    with_pos_perms = db.query(User.id).join(
        UserPosition, UserPosition.user_id == User.id
    ).join(
        PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id
    ).filter(
        PositionAppPerm.app_id == app_id,
        PositionAppPerm.allow == True,  # noqa: E712
        _active_position_filter(),
    )

    return with_roles.union(with_perms).union(with_pos_roles).union(with_pos_perms)


# ── List users ────────────────────────────────────────────────────────────────

@router.get("")
def list_users(
    search: str = Query("", description="(legacy) Búsqueda por nombre, email, username o no. control"),
    q: Optional[str] = Query(None, description="Búsqueda canónica (gana sobre search)"),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="'active' o 'inactive'"),
    app: Optional[str] = Query(None, description="Key de app: usuarios con acceso a esa app"),
    only_staff: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: dict = require_perms("itcj", ["core.users.api.read"]),
    db: DbSession = None,
):
    """Lista usuarios con filtros y paginación."""
    from itcj2.core.models.app import App
    from itcj2.core.models.user import User
    from itcj2.core.models.role import Role
    from itcj2.models.base import paginate
    from sqlalchemy import false

    query = db.query(User)

    if status == "active":
        query = query.filter(User.is_active == True)  # noqa: E712
    elif status == "inactive":
        query = query.filter(User.is_active == False)  # noqa: E712

    term = q if q is not None else search
    if term:
        pattern = f"%{term}%"
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

    if app:
        app_obj = db.query(App).filter_by(key=app).first()
        if app_obj:
            query = query.filter(User.id.in_(_app_access_user_ids(db, app_obj.id)))
        else:
            query = query.filter(false())  # app inexistente → lista vacía

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
        "success": True,
        "data": users_data,
        "total": p.total,
        "page": p.page,
        "per_page": p.per_page,
        "total_pages": p.pages,
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
            raise HTTPException(400, detail="Nombre inválido: proporciona al menos nombre y apellido")
        if len(parts) >= 3:
            first_name = " ".join(parts[:-2]).upper()
            last_name = parts[-2].upper()
            middle_name = parts[-1].upper()
        else:
            first_name = parts[0].upper()
            last_name = parts[-1].upper()
            middle_name = None

    if not (first_name and last_name):
        raise HTTPException(400, detail="El nombre y el apellido son requeridos")

    user_type = body.user_type
    if user_type == "student":
        role_name = "student"
        ctrl = (body.control_number or "").strip()
        if not CONTROL_NUMBER_RE.match(ctrl):
            raise HTTPException(400, detail="Número de control inválido (8 dígitos, o letra seguida de 7 a 9 dígitos)")
        if db.query(User).filter_by(control_number=ctrl).first():
            raise HTTPException(409, detail="El número de control ya está registrado")
    elif user_type == "staff":
        role_name = "staff"
        uname = (body.username or "").strip()
        if not uname:
            raise HTTPException(400, detail="El nombre de usuario es requerido para personal")
        if db.query(User).filter_by(username=uname).first():
            raise HTTPException(409, detail="El nombre de usuario ya está en uso")
    else:
        raise HTTPException(400, detail="Tipo de usuario inválido")

    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        logger.error("create_user: rol por defecto '%s' no encontrado", role_name)
        raise HTTPException(500, detail="Error interno al crear el usuario")

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
            "success": True,
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
        raise HTTPException(409, detail="Valor duplicado: el usuario ya existe")


# ── Create inactive user (inventory flow) ────────────────────────────────────

class CreateInactiveUserBody(BaseModel):
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    email: Optional[str] = None
    username: str
    department_id: int


@router.post("/create-inactive", status_code=201)
def create_inactive_user(
    body: CreateInactiveUserBody,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.create"]),
    db: DbSession = None,
):
    """
    Crea un usuario de planta inactivo vinculado al puesto aux_{dept_code}.
    Usado desde el flujo de registro de equipos en inventario.
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.role import Role
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.department import Department
    from itcj2.core.utils.security import hash_nip
    from sqlalchemy.exc import IntegrityError
    from datetime import date

    dept = db.get(Department, body.department_id)
    if not dept:
        raise HTTPException(400, detail="Departamento no encontrado")

    username = body.username.strip().lower()
    if not username:
        raise HTTPException(400, detail="Username requerido")

    if db.query(User).filter_by(username=username).first():
        raise HTTPException(409, detail=f"El username '{username}' ya está en uso")

    if body.email and db.query(User).filter_by(email=body.email.strip()).first():
        raise HTTPException(409, detail="El correo ya está registrado en el sistema")

    role = db.query(Role).filter_by(name="staff").first()
    if not role:
        raise HTTPException(500, detail="Rol staff no encontrado")

    # Obtener o crear puesto auxiliar del departamento
    aux_code = f"aux_{dept.code}"
    position = db.query(Position).filter_by(code=aux_code).first()
    if not position:
        position = Position(
            code=aux_code,
            title=f"Personal auxiliar — {dept.name}",
            department_id=dept.id,
            allows_multiple=True,
            is_active=True,
            description="Puesto auxiliar para personal sin cargo formal asignado.",
        )
        db.add(position)
        db.flush()

    try:
        new_user = User(
            first_name=body.first_name.strip().upper(),
            last_name=body.last_name.strip().upper(),
            middle_name=body.middle_name.strip().upper() if body.middle_name else None,
            email=body.email.strip() if body.email else None,
            username=username,
            role_id=role.id,
            password_hash=hash_nip(DEFAULT_PASSWORD),
            is_active=False,
            must_change_password=True,
        )
        db.add(new_user)
        db.flush()

        user_position = UserPosition(
            user_id=new_user.id,
            position_id=position.id,
            start_date=date.today(),
            is_active=True,
            notes="Creado automáticamente desde registro de inventario",
        )
        db.add(user_position)
        db.commit()
        db.refresh(new_user)

        logger.info(f"Usuario inactivo '{new_user.full_name}' ({username}) creado por user {int(user['sub'])}")
        return {
            "success": True,
            "message": f"Usuario {new_user.full_name} creado como inactivo",
            "data": {
                "id": new_user.id,
                "full_name": new_user.full_name,
                "username": new_user.username,
                "email": new_user.email,
                "is_active": new_user.is_active,
                "department": {"id": dept.id, "name": dept.name},
            },
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="Username o email duplicado")
    except Exception:
        db.rollback()
        logger.exception("create_inactive_user: fallo al crear usuario")
        raise HTTPException(500, detail="Error interno al crear el usuario")


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
        raise HTTPException(404, detail="Sin departamento asignado")
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
        raise HTTPException(403, detail="No autorizado")

    dept = get_user_department(db, target_user_id)
    if not dept:
        raise HTTPException(404, detail="El usuario no tiene departamento asignado")
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
        raise HTTPException(404, detail="Usuario no encontrado")

    if u.control_number:
        raise HTTPException(400, detail="No se puede resetear la contraseña de un estudiante")

    u.password_hash = hash_nip(DEFAULT_PASSWORD)
    u.must_change_password = True
    db.commit()

    logger.info(f"Contraseña reseteada para usuario {user_id} por {int(current_user['sub'])}")
    return {"success": True, "data": {"user_id": u.id, "must_change_password": True}}


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
        raise HTTPException(404, detail="Usuario no encontrado")

    if int(current_user["sub"]) == u.id:
        raise HTTPException(400, detail="No puedes desactivar tu propia cuenta")

    u.is_active = not u.is_active
    db.commit()

    if not u.is_active:
        # Revocar sesiones del usuario desactivado (invalida sus tokens al instante).
        try:
            from itcj2.core.services.session_service import bump_version
            bump_version(u.id)
        except Exception:
            pass

    action = "activada" if u.is_active else "desactivada"
    logger.info(f"Cuenta de usuario {user_id} {action} por {int(current_user['sub'])}")
    return {"success": True, "data": {"user_id": u.id, "is_active": u.is_active, "message": f"Cuenta {action}"}}


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
        raise HTTPException(404, detail="Usuario no encontrado")

    if body.first_name is not None:
        val = body.first_name.strip()
        if not val:
            raise HTTPException(400, detail="El nombre es requerido")
        u.first_name = val

    if body.last_name is not None:
        val = body.last_name.strip()
        if not val:
            raise HTTPException(400, detail="El apellido es requerido")
        u.last_name = val

    if body.middle_name is not None:
        u.middle_name = body.middle_name.strip() or None

    if body.email is not None:
        u.email = body.email.strip() or None

    if body.username is not None and not u.control_number:
        val = body.username.strip()
        if not val:
            raise HTTPException(400, detail="El nombre de usuario es requerido")
        existing = db.query(User).filter(User.username == val, User.id != user_id).first()
        if existing:
            raise HTTPException(409, detail="El nombre de usuario ya está en uso")
        u.username = val

    if body.control_number is not None and u.control_number is not None:
        val = body.control_number.strip()
        if not CONTROL_NUMBER_RE.match(val):
            raise HTTPException(400, detail="Número de control inválido (8 dígitos, o letra seguida de 7 a 9 dígitos)")
        existing = db.query(User).filter(User.control_number == val, User.id != user_id).first()
        if existing:
            raise HTTPException(409, detail="El número de control ya está registrado")
        u.control_number = val

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="Valor duplicado")

    logger.info(f"Usuario {user_id} actualizado por {int(current_user['sub'])}")
    return {"success": True, "data": u.to_dict()}


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
    from itcj2.core.services.authz_service import user_roles_in_app, has_any_assignment
    from itcj2.models.base import paginate

    # Requiere acceso a helpdesk (cualquier rol/permiso)
    if user.get("role") != "admin" and not has_any_assignment(db, int(user["sub"]), "helpdesk", include_positions=True):
        raise HTTPException(403, detail="No autorizado")

    app = db.query(App).filter_by(key=app_key, is_active=True).first()
    if not app:
        raise HTTPException(404, detail="Aplicación no encontrada")

    user_ids = _app_access_user_ids(db, app.id)

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
        "success": True,
        "data": users_data,
        "total": p.total,
        "page": p.page,
        "per_page": p.per_page,
        "total_pages": p.pages,
    }


# ── Batch: asignaciones por app (C3 core-config-revamp, anti-429) ────────────

@router.get("/apps-summary")
def get_users_apps_summary(
    ids: str = Query("", description="IDs de usuario separados por coma (máx 100)"),
    user: dict = require_perms("itcj", ["core.users.api.read"]),
    db: DbSession = None,
):
    """Apps (activas) con alguna asignación, por usuario — badges de la lista
    de usuarios en 1 request (reemplaza el N+1 de users.js, BUG A)."""
    from itcj2.core.services import authz_service as svc

    raw = [s.strip() for s in ids.split(",") if s.strip()]
    if not raw:
        raise HTTPException(400, detail="Falta el parámetro 'ids'")
    if len(raw) > 100:
        raise HTTPException(400, detail="Máximo 100 IDs por solicitud")
    try:
        user_ids = [int(s) for s in raw]
    except ValueError:
        raise HTTPException(
            400, detail="El parámetro 'ids' debe contener solo números separados por coma"
        )

    return {"success": True, "data": svc.users_apps_summary(db, user_ids)}


@router.get("/{user_id}/app-assignments")
def get_user_app_assignments(
    user_id: int,
    user: dict = require_perms(
        "itcj",
        ["core.authz.api.read.user_roles", "core.authz.api.read.user_permissions"],
    ),
    db: DbSession = None,
):
    """Roles/perms directos/efectivos por app en 1 request (contrato C3).
    Reemplaza los 3 GETs × app de user_detail (BUG A)."""
    from itcj2.core.models.user import User
    from itcj2.core.services import authz_service as svc

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, detail="Usuario no encontrado")

    return {"success": True, "data": svc.user_app_assignments_map(db, user_id)}
