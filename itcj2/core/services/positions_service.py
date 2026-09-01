from __future__ import annotations
import logging
from typing import List, Dict, Optional, Set
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User

logger = logging.getLogger(__name__)


def _bust_user(user_id: int) -> None:
    """Invalida el caché de authz del usuario en todas las apps (F1.1)."""
    try:
        from itcj2.core.services.authz_cache import invalidate_user
        invalidate_user(user_id)
    except Exception:
        pass


def _bust_all() -> None:
    """Invalida TODO el caché de authz. Último recurso, no la vía normal.

    Un cambio de configuración de un puesto afecta SOLO a quienes lo ocupan, así
    que la ruta normal es `_bust_position`. Esto queda como fallback: si no se
    puede resolver la lista de ocupantes, es preferible enfriar caché de más que
    dejar un permiso revocado autorizando hasta AUTHZ_CACHE_TTL.
    """
    try:
        from itcj2.core.services.authz_cache import invalidate_all
        invalidate_all()
    except Exception:
        pass


def position_user_ids(db: Session, position_id: int) -> List[int]:
    """Usuarios con asignación viva al puesto.

    Filtra SOLO por `is_active`, sin las cotas de fecha de
    `authz_service._active_position_filter()`: aquí no se decide autorización
    sino a quién hay que enfriar el caché, y la red ancha es la barata. Un
    ocupante futuro (start_date por venir) tiene cacheado un "no" que el cambio
    no altera; uno cuyo end_date acaba de pasar puede tener una entrada tibia
    que conviene tirar igual.
    """
    return [
        uid
        for (uid,) in db.query(UserPosition.user_id)
        .filter(UserPosition.position_id == position_id, UserPosition.is_active == True)  # noqa: E712
        .distinct()
    ]


def _bust_position(db: Session, position_id: int, app_key: str = None,
                   user_ids: List[int] = None) -> None:
    """Invalida el caché de authz de los OCUPANTES del puesto, no del mundo.

    Cambiar la config de un puesto no cambia los permisos de nadie más, así que
    barrer `authz:v1:{kind}:*` tiraba la caché de las seis apps y de miles de
    usuarios ajenos para propagar un cambio que toca a un puñado. Peor: el
    scan_iter sobre todo el keyspace corre en el hilo único de Redis, compartido
    con Socket.IO, Celery y los holds de AgendaTec.

    - `app_key` dado (assign/remove de rol o permiso EN una app) → se acota
      también a esa app; las otras cinco no se enteraron del cambio.
    - `app_key` None (activar/desactivar/eliminar el puesto) → el puesto puede
      conceder en varias apps, así que se tira el usuario entero.
    - `user_ids` permite capturar a los ocupantes ANTES de una mutación que los
      desasigna (deactivate_position, delete_position); leerlos después
      devolvería la lista vacía y no se invalidaría a nadie.

    Fallback a `_bust_all()` si la lista no se pudo resolver: enfriar de más es
    aceptable; servir un permiso revocado hasta el TTL no lo es.
    """
    try:
        from itcj2.core.services.authz_cache import invalidate_user, invalidate_user_app
        uids = user_ids if user_ids is not None else position_user_ids(db, position_id)
        for uid in uids:
            if app_key:
                invalidate_user_app(uid, app_key)
            else:
                invalidate_user(uid)
    except Exception:
        logger.warning(
            "positions_service: no se pudo acotar la invalidacion del puesto %s; "
            "se cae a invalidate_all()", position_id, exc_info=True,
        )
        _bust_all()


# ---------------------------
# CRUD de Puestos
# ---------------------------

def create_position(
    db: Session,
    code: str,
    title: str,
    description: str = None,
    department_id: int = None,
    allows_multiple: bool = False,
    is_active: bool = True,
    email: str = None,
) -> Position:
    """Crea un nuevo puesto organizacional"""
    if db.query(Position).filter_by(code=code).first():
        raise ValueError(f"Position code '{code}' already exists")

    if email and db.query(Position).filter_by(email=email).first():
        raise ValueError(f"Position email '{email}' already exists")

    position = Position(
        code=code,
        title=title,
        description=description,
        email=email,
        department_id=department_id,
        allows_multiple=allows_multiple,
        is_active=is_active
    )
    logger.info(f"Creating position: {position}")
    db.add(position)
    db.commit()
    return position

def get_position_by_code(db: Session, code: str) -> Optional[Position]:
    """Obtiene un puesto por su código"""
    return db.query(Position).filter_by(code=code, is_active=True).first()

def list_positions(db: Session, department=None) -> List[Position]:
    """Lista todos los puestos activos, opcionalmente filtrados por departamento"""
    query = db.query(Position).filter_by(is_active=True)
    if department:
        if hasattr(department, 'id'):
            query = query.filter_by(department_id=department.id)
        elif isinstance(department, int):
            query = query.filter_by(department_id=department)
        else:
            try:
                dept_id = int(department)
                query = query.filter_by(department_id=dept_id)
            except (ValueError, TypeError):
                pass
    return query.order_by(Position.title.asc()).all()

def update_position(db: Session, position_id: int, **kwargs) -> Position:
    """Actualiza un puesto organizacional"""
    position = db.get(Position, position_id)
    if not position:
        raise ValueError("not_found")

    allowed_fields = ['title', 'description', 'email', 'is_active', 'allows_multiple']
    for key, value in kwargs.items():
        if key in allowed_fields and hasattr(position, key):
            setattr(position, key, value)

    db.commit()
    # Cambiar is_active de un puesto afecta el acceso de sus usuarios. Las
    # asignaciones siguen vivas, así que los ocupantes se pueden leer después
    # del commit. Sin app_key: el puesto puede conceder en varias apps.
    if 'is_active' in kwargs:
        _bust_position(db, position_id)
    return position

def deactivate_position(db: Session, position_id: int) -> bool:
    """Desactiva un puesto y todas sus asignaciones activas"""
    position = db.get(Position, position_id)
    if not position:
        return False

    position.is_active = False

    # ANTES del UPDATE: en cuanto is_active pase a False la consulta de
    # ocupantes devuelve vacío y no se invalidaría a nadie.
    afectados = position_user_ids(db, position_id)

    db.query(UserPosition).filter_by(
        position_id=position_id,
        is_active=True
    ).update({
        'is_active': False,
        'end_date': date.today()
    })

    db.commit()
    _bust_position(db, position_id, user_ids=afectados)
    return True

def delete_position(db: Session, position_id: int) -> bool:
    """Elimina un puesto completamente (CASCADE)"""
    position = db.get(Position, position_id)
    if not position:
        return False

    # ANTES del delete: el CASCADE se lleva las filas de UserPosition.
    afectados = position_user_ids(db, position_id)

    db.delete(position)
    db.commit()
    _bust_position(db, position_id, user_ids=afectados)
    return True

def get_position_by_id(db: Session, position_id: int) -> Optional[Position]:
    """Obtiene un puesto por ID"""
    return db.get(Position, position_id)

# ---------------------------
# Asignación de Usuarios a Puestos
# ---------------------------

def assign_user_to_position(
    db: Session,
    user_id: int,
    position_id: int,
    start_date: date = None,
    notes: str = None,
) -> UserPosition:
    """Asigna un usuario a un puesto"""
    if not start_date:
        start_date = date.today()

    position = db.get(Position, position_id)
    if not position:
        raise ValueError("Position not found")

    existing = db.query(UserPosition).filter_by(
        user_id=user_id,
        position_id=position_id,
        is_active=True
    ).first()

    if existing:
        raise ValueError("User already has this position assigned")

    if not position.allows_multiple:
        current_assignment = db.query(UserPosition).filter_by(
            position_id=position_id,
            is_active=True
        ).first()

        if current_assignment:
            raise ValueError("This position already has an active user and does not allow multiple assignments")

    assignment = UserPosition(
        user_id=user_id,
        position_id=position_id,
        start_date=start_date,
        notes=notes
    )

    db.add(assignment)
    db.commit()
    _bust_user(user_id)
    return assignment

def remove_user_from_position(db: Session, user_id: int, position_id: int, end_date: date = None) -> bool:
    """Remueve un usuario de un puesto"""
    if not end_date:
        end_date = date.today()

    assignment = db.query(UserPosition).filter_by(
        user_id=user_id,
        position_id=position_id,
        is_active=True
    ).first()

    if not assignment:
        return False

    assignment.is_active = False
    assignment.end_date = end_date
    db.commit()
    _bust_user(user_id)
    return True

def transfer_position(
    db: Session,
    old_user_id: int,
    new_user_id: int,
    position_id: int,
    transfer_date: date = None,
) -> bool:
    """Transfiere un puesto de un usuario a otro"""
    if not transfer_date:
        transfer_date = date.today()

    remove_user_from_position(db, old_user_id, position_id, transfer_date)
    assign_user_to_position(db, new_user_id, position_id, transfer_date)

    return True

def get_user_active_positions(db: Session, user_id: int) -> List[Dict]:
    """Obtiene todos los puestos activos de un usuario"""
    from itcj2.core.services.departments_service import _active_position_window

    assignments = (
        db.query(UserPosition, Position)
        .join(Position)
        .filter(
            UserPosition.user_id == user_id,
            _active_position_window(),
            Position.is_active == True
        )
        .order_by(UserPosition.start_date.asc(), UserPosition.position_id.asc())
        .all()
    )

    return [{
        'position_id': pos.id,
        'code': pos.code,
        'title': pos.title,
        'department': {
            'id': pos.department.id,
            'name': pos.department.name,
            'code': pos.department.code
        } if pos.department else None,
        'start_date': assignment.start_date,
        'notes': assignment.notes
    } for assignment, pos in assignments]

def get_position_current_users(db: Session, position_id: int) -> List[Dict]:
    """Obtiene TODOS los usuarios actualmente asignados a un puesto (para puestos múltiples)"""
    from itcj2.core.services.departments_service import _active_position_window

    assignments = (
        db.query(UserPosition, User)
        .join(User)
        .filter(
            UserPosition.position_id == position_id,
            _active_position_window()
        )
        .order_by(UserPosition.start_date.asc(), UserPosition.user_id.asc())
        .all()
    )

    return [{
        'user_id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'start_date': assignment.start_date,
        'notes': assignment.notes
    } for assignment, user in assignments]

def get_position_current_user(db: Session, position_id: int) -> Optional[Dict]:
    """Obtiene el primer usuario (para puestos únicos) o None"""
    users = get_position_current_users(db, position_id)
    return users[0] if users else None

# ---------------------------
# Permisos por Puesto
# ---------------------------

def assign_role_to_position(db: Session, position_id: int, app_key: str, role_name: str) -> bool:
    """Asigna un rol a un puesto en una aplicación específica"""
    from itcj2.core.services.authz_service import get_or_404_app, get_role_by_name

    app = get_or_404_app(db, app_key)
    role = get_role_by_name(db, role_name)

    if not role:
        raise ValueError(f"Role '{role_name}' does not exist")

    existing = db.query(PositionAppRole).filter_by(
        position_id=position_id,
        app_id=app.id,
        role_id=role.id
    ).first()

    if existing:
        return False

    assignment = PositionAppRole(
        position_id=position_id,
        app_id=app.id,
        role_id=role.id
    )

    db.add(assignment)
    db.commit()
    _bust_position(db, position_id, app_key)  # los ocupantes ganan el rol en ESTA app
    return True

def remove_role_from_position(db: Session, position_id: int, app_key: str, role_name: str) -> bool:
    """Remueve un rol de un puesto"""
    from itcj2.core.services.authz_service import get_or_404_app, get_role_by_name

    app = get_or_404_app(db, app_key)
    role = get_role_by_name(db, role_name)

    if not role:
        return False

    deleted = db.query(PositionAppRole).filter_by(
        position_id=position_id,
        app_id=app.id,
        role_id=role.id
    ).delete()

    db.commit()
    if deleted:
        _bust_position(db, position_id, app_key)  # los ocupantes pierden el rol en ESTA app
    return deleted > 0

def assign_permission_to_position(
    db: Session,
    position_id: int,
    app_key: str,
    perm_code: str,
    allow: bool = True,
) -> bool:
    """Asigna un permiso directo a un puesto"""
    from itcj2.core.services.authz_service import get_or_404_app, get_perm

    app = get_or_404_app(db, app_key)
    perm = get_perm(db, app.id, perm_code)

    if not perm:
        raise ValueError(f"Permission '{perm_code}' does not exist in app '{app_key}'")

    existing = db.query(PositionAppPerm).filter_by(
        position_id=position_id,
        app_id=app.id,
        perm_id=perm.id
    ).first()

    if existing:
        existing.allow = allow
        db.commit()
        _bust_position(db, position_id, app_key)  # cambia el permiso en ESTA app
        return True

    assignment = PositionAppPerm(
        position_id=position_id,
        app_id=app.id,
        perm_id=perm.id,
        allow=allow
    )

    db.add(assignment)
    db.commit()
    _bust_position(db, position_id, app_key)  # los ocupantes ganan el permiso en ESTA app
    return True

def get_position_effective_permissions(db: Session, user_id: int, app_key: str) -> Set[str]:
    """Obtiene todos los permisos efectivos de un usuario basados en sus puestos"""
    from itcj2.core.services.authz_service import get_or_404_app
    from itcj2.core.models.role_permission import RolePermission

    app = get_or_404_app(db, app_key)

    active_position_ids = [
        p_id[0] for p_id in db.query(UserPosition.position_id)
        .filter_by(user_id=user_id, is_active=True)
        .all()
    ]

    if not active_position_ids:
        return set()

    perms_via_roles = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
        .filter(
            PositionAppRole.position_id.in_(active_position_ids),
            PositionAppRole.app_id == app.id,
            Permission.app_id == app.id
        )
        .all()
    )

    direct_perms = (
        db.query(Permission.code)
        .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
        .filter(
            PositionAppPerm.position_id.in_(active_position_ids),
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
            Permission.app_id == app.id
        )
        .all()
    )

    all_perms = set()
    all_perms.update(p[0] for p in perms_via_roles)
    all_perms.update(p[0] for p in direct_perms)

    return all_perms

def get_position_assignments(db: Session, position_id: int) -> Dict:
    """Obtiene todas las asignaciones de un puesto por aplicación"""
    position = db.get(Position, position_id)
    if not position:
        raise ValueError("Position not found")

    # Obtener app_ids únicos de roles
    role_app_ids = set(
        row[0] for row in db.query(PositionAppRole.app_id)
        .filter_by(position_id=position_id)
        .distinct()
        .all()
    )

    # Obtener app_ids únicos de permisos
    perm_app_ids = set(
        row[0] for row in db.query(PositionAppPerm.app_id)
        .filter_by(position_id=position_id)
        .distinct()
        .all()
    )

    all_app_ids = role_app_ids.union(perm_app_ids)

    if not all_app_ids:
        return {}

    apps_with_assignments = (
        db.query(App)
        .filter(App.id.in_(all_app_ids))
        .all()
    )

    apps_data = {}
    for app in apps_with_assignments:
        roles = (
            db.query(Role.name)
            .join(PositionAppRole)
            .filter(
                PositionAppRole.position_id == position_id,
                PositionAppRole.app_id == app.id
            )
            .all()
        )

        perms = (
            db.query(Permission.code)
            .join(PositionAppPerm)
            .filter(
                PositionAppPerm.position_id == position_id,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True
            )
            .all()
        )

        apps_data[app.key] = {
            'app_name': app.name,
            'roles': [r[0] for r in roles],
            'direct_permissions': [p[0] for p in perms]
        }

    return {
        'position': {
            'id': position.id,
            'code': position.code,
            'title': position.title,
            'department': {
                'id': position.department.id,
                'name': position.department.name,
                'code': position.department.code
            } if position.department else None
        },
        'current_user': get_position_current_user(db, position_id),
        'apps': apps_data
    }

def get_user_managed_departments(db: Session, user_id: int) -> List[Dict]:
    """Obtiene los departamentos que maneja un usuario como jefe"""
    from itcj2.core.models.department import Department

    from itcj2.core.services.departments_service import _active_position_window

    head_assignments = (
        db.query(UserPosition, Position, Department)
        .join(Position, UserPosition.position_id == Position.id)
        .join(Department, Position.department_id == Department.id)
        .filter(
            UserPosition.user_id == user_id,
            # Vigencia real (no solo is_active): de aquí sale la raíz del subárbol
            # y del scope del dashboard del jefe. Una jefatura vencida no manda.
            _active_position_window(),
            Position.is_active == True,
            or_(
                Position.code.like('head_%'),
                Position.code.like('subdirector_%'),
                Position.code.like('director')
            ),
            Department.is_active == True
        )
        # Orden determinista: `get_user_primary_managed_department` toma el [0] y
        # sin ORDER BY quien encabeza dos departamentos veía un subárbol distinto
        # según lo que devolviera Postgres.
        .order_by(UserPosition.start_date.asc(), UserPosition.position_id.asc())
        .all()
    )

    return [{
        'department': {
            'id': department.id,
            'code': department.code,
            'name': department.name,
            'description': department.description,
            'icon_class': department.icon_class,
            'is_active': department.is_active,
            'parent_id': department.parent_id
        },
        'position': {
            'id': position.id,
            'code': position.code,
            'title': position.title
        },
        'assignment': {
            'start_date': assignment.start_date,
            'notes': assignment.notes
        }
    } for assignment, position, department in head_assignments]

def get_user_primary_managed_department(db: Session, user_id: int) -> Optional[Dict]:
    """Obtiene el departamento principal que maneja un usuario como jefe (el primero si hay varios)"""
    departments = get_user_managed_departments(db, user_id)
    return departments[0] if departments else None
