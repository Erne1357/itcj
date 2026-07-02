from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from itcj2.core.models.department import Department


def _bust_dept_map() -> None:
    """Invalida el cache del mapa de descendientes tras mutar el árbol. Best-effort."""
    try:
        from itcj2.core.services.authz_cache import invalidate_dept_map
        invalidate_dept_map()
    except Exception:
        pass


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


def create_department(db: Session, code: str, name: str, description=None, parent_id=None,
                      icon_class=None, is_official: bool = False):
    """Crea un departamento. `is_official` False por defecto: lo creado en runtime por la
    UI es un sub-departamento tuyo; los oficiales vienen del seed (todos True por migración).
    Un admin puede pasar is_official=True para dar de alta uno oficial."""
    if db.query(Department).filter_by(code=code).first():
        raise ValueError("department_code_exists")

    dept = Department(
        code=code,
        name=name,
        description=description,
        parent_id=parent_id,
        icon_class=icon_class,
        is_official=is_official,
    )
    db.add(dept)
    db.commit()
    _bust_dept_map()
    return dept


def update_department(db: Session, dept_id: int, **kwargs):
    dept = get_department(db, dept_id)
    if not dept:
        raise ValueError("not_found")

    if "parent_id" in kwargs and kwargs["parent_id"] is not None:
        new_parent = kwargs["parent_id"]
        if new_parent == dept_id:
            raise ValueError("cycle_detected")
        # No permitir anclar el dept bajo uno de sus propios descendientes.
        from itcj2.core.services.hierarchy_service import descendant_department_ids
        if new_parent in descendant_department_ids(db, dept_id, include_self=False):
            raise ValueError("cycle_detected")

    for key, value in kwargs.items():
        if hasattr(dept, key):
            setattr(dept, key, value)

    db.commit()
    _bust_dept_map()
    return dept


def get_department_positions(db: Session, dept_id: int):
    from itcj2.core.services import positions_service
    department = get_department(db, dept_id)
    if not department:
        raise ValueError("not_found")
    return positions_service.list_positions(db, department=department)


def _active_position_window():
    """Filtro canónico de puesto vigente: activo y dentro de [start_date, end_date].

    Reemplaza el patrón disperso ``is_active == True`` que ignoraba end_date/start_date.
    """
    from sqlalchemy import and_, or_
    from itcj2.core.models.position import UserPosition
    return and_(
        UserPosition.is_active == True,  # noqa: E712
        or_(UserPosition.end_date.is_(None), UserPosition.end_date >= func.current_date()),
        UserPosition.start_date <= func.current_date(),
    )


def get_user_departments(db: Session, user_id: int) -> list:
    """TODOS los departamentos donde el usuario tiene un puesto vigente (deduped).

    Resolver canónico multi-puesto. Antes había 3 implementaciones divergentes
    (User.get_current_position sin orden, este por start_date, helpdesk por .first());
    todas deben delegar aquí.
    """
    from itcj2.core.models.position import Position, UserPosition
    rows = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            _active_position_window(),
            UserPosition.user_id == user_id,
            Position.department_id.isnot(None),
        )
        .distinct()
        .all()
    )
    dept_ids = [r[0] for r in rows]
    if not dept_ids:
        return []
    return (
        db.query(Department)
        .filter(Department.id.in_(dept_ids))
        .order_by(Department.name)
        .all()
    )


def get_primary_user_department(db: Session, user_id: int):
    """Departamento 'primario' con tiebreak determinista (start_date ASC, position_id ASC).

    Para consumidores que necesitan UN solo departamento (el patrón viejo). Prefiere
    ``get_user_departments`` cuando el scope es multi-depto.
    """
    from itcj2.core.models.position import Position, UserPosition
    row = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            _active_position_window(),
            UserPosition.user_id == user_id,
            Position.department_id.isnot(None),
        )
        .order_by(UserPosition.start_date.asc(), UserPosition.position_id.asc())
        .first()
    )
    if not row:
        return None
    return db.get(Department, row[0])


def get_user_department(db: Session, user_id: int):
    """Compat: delega en el resolver primario canónico."""
    return get_primary_user_department(db, user_id)
