# itcj/core/services/departments_service.py
from itcj.core.models.department import Department
from itcj.core.extensions import db

def list_subdirections():
    """Obtiene solo las subdirecciones (departamentos padres)"""
    return Department.query.filter_by(
        parent_id=None,
        is_active=True
    ).order_by(Department.name).all()

def list_departments_by_parent(parent_id=None):
    """Obtiene departamentos por subdirección"""
    if parent_id:
        return Department.query.filter_by(
            parent_id=parent_id,
            is_active=True
        ).order_by(Department.name).all()
    else:
        # Si no hay parent_id, devolver subdirecciones
        return list_subdirections()

def list_departments():
    """Lista todos los departamentos (para admin)"""
    return Department.query.filter_by(is_active=True).order_by(Department.name).all()

def get_department(dept_id):
    """Obtiene un departamento por ID"""
    return Department.query.get(dept_id)

def create_department(code, name, description=None, parent_id=None, icon_class=None):
    """Crea un nuevo departamento"""
    if Department.query.filter_by(code=code).first():
        raise ValueError("department_code_exists")
    
    dept = Department(
        code=code,
        name=name,
        description=description,
        parent_id=parent_id,
        icon_class=icon_class
    )
    db.session.add(dept)
    db.session.commit()
    return dept

def update_department(dept_id, **kwargs):
    """Actualiza un departamento"""
    dept = get_department(dept_id)
    if not dept:
        raise ValueError("not_found")
    
    for key, value in kwargs.items():
        if hasattr(dept, key):
            setattr(dept, key, value)
    
    db.session.commit()
    return dept

def get_department_positions(dept_id):
    """Obtiene puestos de un departamento"""
    from itcj.core.services import positions_service
    department = get_department(dept_id)
    if not department:
        raise ValueError("not_found")
    return positions_service.list_positions(department=department)

def get_user_department(user_id):
    """Obtiene el primer departamento asignado a un usuario según sus puestos activos"""
    from itcj.core.models.position import UserPosition
    from itcj.core.models.department import Department
    # Busca el primer UserPosition activo del usuario, ordenado por fecha de inicio
    user_position = UserPosition.query.filter_by(
        user_id=user_id,
        is_active=True
    ).order_by(UserPosition.start_date.asc()).first()
    if user_position and user_position.position and user_position.position.department_id:
        return Department.query.get(user_position.position.department_id)
    return None