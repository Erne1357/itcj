from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from itcj2.core.models.department import Department


def get_direction(db: Session):
    return db.query(Department).filter_by(code='direction', is_active=True).first()


def get_union_delegation(db: Session):
    return db.query(Department).filter_by(code='union_delegation', is_active=True).first()


def list_subdirections(db: Session):
    direction = get_direction(db)
    if direction:
        return (
            db.query(Department)
            .filter_by(parent_id=direction.id, is_active=True)
            .order_by(Department.name)
            .all()
        )
    return []


def list_departments_by_parent(db: Session, parent_id=None):
    if parent_id:
        return (
            db.query(Department)
            .filter_by(parent_id=parent_id, is_active=True)
            .order_by(Department.name)
            .all()
        )
    return list_subdirections(db)


def list_parent_options(db: Session):
    direction = get_direction(db)
    if not direction:
        return []
    options = [direction]
    options.extend(list_subdirections(db))
    return options


def list_departments(db: Session):
    return db.query(Department).filter_by(is_active=True).order_by(Department.name).all()


def get_department(db: Session, dept_id: int):
    return db.get(Department, dept_id)


def create_department(db: Session, code: str, name: str, description=None, parent_id=None, icon_class=None):
    if db.query(Department).filter_by(code=code).first():
        raise ValueError("department_code_exists")

    dept = Department(
        code=code,
        name=name,
        description=description,
        parent_id=parent_id,
        icon_class=icon_class,
    )
    db.add(dept)
    db.commit()
    return dept


def update_department(db: Session, dept_id: int, **kwargs):
    dept = get_department(db, dept_id)
    if not dept:
        raise ValueError("not_found")

    for key, value in kwargs.items():
        if hasattr(dept, key):
            setattr(dept, key, value)

    db.commit()
    return dept


def get_department_positions(db: Session, dept_id: int):
    from itcj2.core.services import positions_service
    department = get_department(db, dept_id)
    if not department:
        raise ValueError("not_found")
    return positions_service.list_positions(db, department=department)


def get_user_department(db: Session, user_id: int):
    from itcj2.core.models.position import UserPosition
    user_position = (
        db.query(UserPosition)
        .filter_by(user_id=user_id, is_active=True)
        .order_by(UserPosition.start_date.asc())
        .first()
    )
    if user_position and user_position.position and user_position.position.department_id:
        return db.get(Department, user_position.position.department_id)
    return None
