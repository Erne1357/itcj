# itcj/core/services/departments_service.py
from typing import List, Dict, Optional
from itcj.core.extensions import db
from itcj.core.models.department import Department
from itcj.core.models.position import Position

def create_department(code: str, name: str, description: str = None) -> Department:
    """Crea un nuevo departamento"""
    if db.session.query(Department).filter_by(code=code).first():
        raise ValueError(f"Department code '{code}' already exists")
    
    dept = Department(code=code, name=name, description=description)
    db.session.add(dept)
    db.session.commit()
    return dept

def list_departments(active_only: bool = True) -> List[Department]:
    """Lista todos los departamentos"""
    query = db.session.query(Department)
    if active_only:
        query = query.filter_by(is_active=True)
    return query.order_by(Department.name).all()

def get_department(dept_id: int) -> Optional[Department]:
    """Obtiene un departamento por ID"""
    return db.session.query(Department).get(dept_id)

def get_department_by_code(code: str) -> Optional[Department]:
    """Obtiene un departamento por código"""
    return db.session.query(Department).filter_by(code=code, is_active=True).first()

def update_department(dept_id: int, **kwargs) -> Department:
    """Actualiza un departamento"""
    dept = db.session.query(Department).get(dept_id)
    if not dept:
        raise ValueError("Department not found")
    
    for key, value in kwargs.items():
        if hasattr(dept, key):
            setattr(dept, key, value)
    
    db.session.commit()
    return dept

def get_department_positions(dept_id: int) -> List[Dict]:
    """Obtiene todos los puestos de un departamento con su información"""
    from itcj.core.services.positions_service import get_position_current_user
    
    positions = (
        db.session.query(Position)
        .filter_by(department_id=dept_id, is_active=True)
        .order_by(Position.title)
        .all()
    )
    
    return [{
        'id': p.id,
        'code': p.code,
        'title': p.title,
        'description': p.description,
        'is_active': p.is_active,
        'current_user': get_position_current_user(p.id)
    } for p in positions]