# itcj/core/services/positions_service.py
from __future__ import annotations
from typing import List, Dict, Optional, Set
from datetime import date, datetime
from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from itcj.core.extensions import db
from itcj.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.user import User
import logging

# ---------------------------
# CRUD de Puestos
# ---------------------------

def create_position(code: str, title: str, description: str = None, department_id: int = None, allows_multiple: bool = False, is_active: bool = True, email: str = None) -> Position:
    """Crea un nuevo puesto organizacional"""
    if db.session.query(Position).filter_by(code=code).first():
        raise ValueError(f"Position code '{code}' already exists")
    
    # Verificar email único si se proporciona
    if email and db.session.query(Position).filter_by(email=email).first():
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
    current_app.logger.info(f"Creating position: {position}")
    db.session.add(position)
    db.session.commit()
    return position

def get_position_by_code(code: str) -> Optional[Position]:
    """Obtiene un puesto por su código"""
    return db.session.query(Position).filter_by(code=code, is_active=True).first()

def list_positions(department=None) -> List[Position]:
    """Lista todos los puestos activos, opcionalmente filtrados por departamento"""
    query = db.session.query(Position).filter_by(is_active=True)
    if department:
        # department puede ser un ID (int) o un objeto Department
        if hasattr(department, 'id'):
            query = query.filter_by(department_id=department.id)
        elif isinstance(department, int):
            query = query.filter_by(department_id=department)
        else:
            # Si es string, asumir que es department_id como int
            try:
                dept_id = int(department)
                query = query.filter_by(department_id=dept_id)
            except (ValueError, TypeError):
                pass
    return query.order_by(Position.title.asc()).all()

def update_position(position_id: int, **kwargs) -> Position:
    """Actualiza un puesto"""
    position = db.session.query(Position).get(position_id)
    if not position:
        raise ValueError("Position not found")
    
    for key, value in kwargs.items():
        if hasattr(position, key):
            setattr(position, key, value)
    
    db.session.commit()
    return position

def deactivate_position(position_id: int) -> bool:
    """Desactiva un puesto y todas sus asignaciones activas"""
    position = db.session.query(Position).get(position_id)
    if not position:
        return False
    
    # Desactivar el puesto
    position.is_active = False
    
    # Desactivar todas las asignaciones de usuarios activas
    db.session.query(UserPosition).filter_by(
        position_id=position_id, 
        is_active=True
    ).update({
        'is_active': False,
        'end_date': date.today()
    })
    
    db.session.commit()
    return True

# ---------------------------
# Asignación de Usuarios a Puestos
# ---------------------------

def assign_user_to_position(user_id: int, position_id: int, start_date: date = None, notes: str = None) -> UserPosition:
    """Asigna un usuario a un puesto"""
    if not start_date:
        start_date = date.today()
    
    position = db.session.query(Position).get(position_id)
    if not position:
        raise ValueError("Position not found")
    
    # Verificar si el usuario ya tiene este puesto
    existing = db.session.query(UserPosition).filter_by(
        user_id=user_id,
        position_id=position_id,
        is_active=True
    ).first()
    
    if existing:
        raise ValueError("User already has this position assigned")
    
    # NUEVO: Si el puesto NO permite múltiples usuarios, verificar que no haya otro usuario
    if not position.allows_multiple:
        current_assignment = db.session.query(UserPosition).filter_by(
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
    
    db.session.add(assignment)
    db.session.commit()
    return assignment

def remove_user_from_position(user_id: int, position_id: int, end_date: date = None) -> bool:
    """Remueve un usuario de un puesto"""
    if not end_date:
        end_date = date.today()
    
    assignment = db.session.query(UserPosition).filter_by(
        user_id=user_id,
        position_id=position_id,
        is_active=True
    ).first()
    
    if not assignment:
        return False
    
    assignment.is_active = False
    assignment.end_date = end_date
    db.session.commit()
    return True

def transfer_position(old_user_id: int, new_user_id: int, position_id: int, transfer_date: date = None) -> bool:
    """Transfiere un puesto de un usuario a otro"""
    if not transfer_date:
        transfer_date = date.today()
    
    # Remover al usuario anterior
    remove_user_from_position(old_user_id, position_id, transfer_date)
    
    # Asignar al nuevo usuario
    assign_user_to_position(new_user_id, position_id, transfer_date)
    
    return True

def get_user_active_positions(user_id: int) -> List[Dict]:
    """Obtiene todos los puestos activos de un usuario"""
    assignments = (
        db.session.query(UserPosition, Position)
        .join(Position)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True
        )
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

def get_position_current_users(position_id: int) -> List[Dict]:
    """Obtiene TODOS los usuarios actualmente asignados a un puesto (para puestos múltiples)"""
    assignments = (
        db.session.query(UserPosition, User)
        .join(User)
        .filter(
            UserPosition.position_id == position_id,
            UserPosition.is_active == True
        )
        .all()
    )
    
    return [{
        'user_id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'start_date': assignment.start_date,
        'notes': assignment.notes
    } for assignment, user in assignments]

# MANTENER la función original para compatibilidad con puestos únicos
def get_position_current_user(position_id: int) -> Optional[Dict]:
    """Obtiene el primer usuario (para puestos únicos) o None"""
    users = get_position_current_users(position_id)
    return users[0] if users else None

# ---------------------------
# Permisos por Puesto
# ---------------------------

def assign_role_to_position(position_id: int, app_key: str, role_name: str) -> bool:
    """Asigna un rol a un puesto en una aplicación específica"""
    from itcj.core.services.authz_service import get_or_404_app, get_role_by_name
    
    app = get_or_404_app(app_key)
    role = get_role_by_name(role_name)
    
    if not role:
        raise ValueError(f"Role '{role_name}' does not exist")
    
    # Verificar si ya existe
    existing = db.session.query(PositionAppRole).filter_by(
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
    
    db.session.add(assignment)
    db.session.commit()
    return True

def remove_role_from_position(position_id: int, app_key: str, role_name: str) -> bool:
    """Remueve un rol de un puesto"""
    from itcj.core.services.authz_service import get_or_404_app, get_role_by_name
    
    app = get_or_404_app(app_key)
    role = get_role_by_name(role_name)
    
    if not role:
        return False
    
    deleted = db.session.query(PositionAppRole).filter_by(
        position_id=position_id,
        app_id=app.id,
        role_id=role.id
    ).delete()
    
    db.session.commit()
    return deleted > 0

def assign_permission_to_position(position_id: int, app_key: str, perm_code: str, allow: bool = True) -> bool:
    """Asigna un permiso directo a un puesto"""
    from itcj.core.services.authz_service import get_or_404_app, get_perm
    
    app = get_or_404_app(app_key)
    perm = get_perm(app.id, perm_code)
    
    if not perm:
        raise ValueError(f"Permission '{perm_code}' does not exist in app '{app_key}'")
    
    # Verificar si ya existe y actualizar
    existing = db.session.query(PositionAppPerm).filter_by(
        position_id=position_id,
        app_id=app.id,
        perm_id=perm.id
    ).first()
    
    if existing:
        existing.allow = allow
        db.session.commit()
        return True
    
    assignment = PositionAppPerm(
        position_id=position_id,
        app_id=app.id,
        perm_id=perm.id,
        allow=allow
    )
    
    db.session.add(assignment)
    db.session.commit()
    return True

def get_position_effective_permissions(user_id: int, app_key: str) -> Set[str]:
    """Obtiene todos los permisos efectivos de un usuario basados en sus puestos"""
    from itcj.core.services.authz_service import get_or_404_app
    from itcj.core.models.role_permission import RolePermission
    
    app = get_or_404_app(app_key)
    
    # Obtener IDs de puestos activos del usuario
    active_position_ids = [
        p_id[0] for p_id in db.session.query(UserPosition.position_id)
        .filter_by(user_id=user_id, is_active=True)
        .all()
    ]
    
    if not active_position_ids:
        return set()
    
    # Permisos via roles de puesto
    # PositionAppRole → RolePermission → Permission (filtrado por app_id)
    perms_via_roles = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
        .filter(
            PositionAppRole.position_id.in_(active_position_ids),
            PositionAppRole.app_id == app.id,
            Permission.app_id == app.id  # ← FILTRO CRÍTICO FALTANTE
        )
        .all()
    )
    
    # Permisos directos de puesto (ya están bien filtrados)
    direct_perms = (
        db.session.query(Permission.code)
        .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
        .filter(
            PositionAppPerm.position_id.in_(active_position_ids),
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
            Permission.app_id == app.id  # Este ya estaba, pero lo dejo explícito
        )
        .all()
    )
    
    all_perms = set()
    all_perms.update(p[0] for p in perms_via_roles)
    all_perms.update(p[0] for p in direct_perms)
    
    return all_perms

def get_position_assignments(position_id: int) -> Dict:
    """Obtiene todas las asignaciones de un puesto por aplicación"""
    position = db.session.query(Position).get(position_id)
    if not position:
        raise ValueError("Position not found")
    
    apps_data = {}
    
    # Método más simple: obtener IDs de apps por separado y luego hacer query
    # Obtener app_ids únicos de roles
    role_app_ids = set(
        row[0] for row in db.session.query(PositionAppRole.app_id)
        .filter_by(position_id=position_id)
        .distinct()
        .all()
    )
    
    # Obtener app_ids únicos de permisos
    perm_app_ids = set(
        row[0] for row in db.session.query(PositionAppPerm.app_id)
        .filter_by(position_id=position_id)
        .distinct()
        .all()
    )
    
    # Combinar IDs únicos
    all_app_ids = role_app_ids.union(perm_app_ids)
    
    # Si no hay asignaciones, devolver diccionario vacío
    if not all_app_ids:
        return {}
    
    # Obtener las aplicaciones
    apps_with_assignments = (
        db.session.query(App)
        .filter(App.id.in_(all_app_ids))
        .all()
    )
    
    for app in apps_with_assignments:
        # Roles
        roles = (
            db.session.query(Role.name)
            .join(PositionAppRole)
            .filter(
                PositionAppRole.position_id == position_id,
                PositionAppRole.app_id == app.id
            )
            .all()
        )
        
        # Permisos directos
        perms = (
            db.session.query(Permission.code)
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
        'current_user': get_position_current_user(position_id),
        'apps': apps_data
    }

def get_position_by_id(position_id):
    """Obtiene un puesto por ID"""
    from itcj.core.models.position import Position
    return Position.query.get(position_id)

def delete_position(position_id):
    """Elimina un puesto completamente (CASCADE)"""
    from itcj.core.models.position import Position
    
    position = Position.query.get(position_id)
    if not position:
        return False
    
    db.session.delete(position)
    db.session.commit()
    return True

def update_position(position_id, **kwargs):
    """Actualiza un puesto organizacional"""
    position = get_position_by_id(position_id)
    if not position:
        raise ValueError("not_found")
    
    # Campos permitidos para actualización
    allowed_fields = ['title', 'description', 'email', 'is_active', 'allows_multiple']
    
    for key, value in kwargs.items():
        if key in allowed_fields and hasattr(position, key):
            setattr(position, key, value)
    
    db.session.commit()
    return position

def get_user_managed_departments(user_id: int) -> List[Dict]:
    """Obtiene los departamentos que maneja un usuario como jefe"""
    from itcj.core.models.department import Department
    
    # Buscar asignaciones activas del usuario que sean de jefe de departamento
    head_assignments = (
        db.session.query(UserPosition, Position, Department)
        .join(Position, UserPosition.position_id == Position.id)
        .join(Department, Position.department_id == Department.id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True,
            or_(Position.code.like('head_%'),Position.code.like('subdirector_%'),Position.code.like('director')),  # Filtrar solo puestos de jefe
            Department.is_active == True
        )
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

def get_user_primary_managed_department(user_id: int) -> Optional[Dict]:
    """Obtiene el departamento principal que maneja un usuario como jefe (el primero si hay varios)"""
    departments = get_user_managed_departments(user_id)
    return departments[0] if departments else None