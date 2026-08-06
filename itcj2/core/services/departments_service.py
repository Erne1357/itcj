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


def list_parent_options(db: Session, exclude_subtree_of: int | None = None) -> list[dict]:
    """Árbol activo COMPLETO aplanado (preorden DFS) con depth para indentar.

    Reemplaza el cap histórico [direction + subdirections]: cualquier depto
    activo puede ser padre (POST /departments nunca tuvo cap de profundidad, y
    ahora incluye también el subtree de union_delegation, antes omitido).

    ``exclude_subtree_of``: en modo edición excluye ese depto Y todo su subtree
    (anti-ciclo en UI; el guard duro sigue en update_department).

    Claves legacy conservadas para departments.js: id, name, parent_id.
    Nota: parent_id refleja la posición EN EL ÁRBOL (None para nodos tratados
    como raíz por tener parent inactivo), no siempre el valor crudo de BD.
    """
    excluded: set[int] = set()
    if exclude_subtree_of is not None:
        from itcj2.core.services.hierarchy_service import descendant_department_ids
        excluded = descendant_department_ids(db, exclude_subtree_of, include_self=True)

    flat: list[dict] = []

    def _walk(nodes: list[dict], parent_id) -> None:
        for n in nodes:
            if n["id"] in excluded:
                continue  # excluye el nodo y TODO su subtree
            flat.append({
                "id": n["id"],
                "name": n["name"],
                "code": n["code"],
                "parent_id": parent_id,
                "depth": n["depth"],
                "is_official": n["is_official"],
            })
            _walk(n["children"], n["id"])

    _walk(build_tree(db), None)
    return flat


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

    if parent_id is not None:
        parent = db.get(Department, parent_id)
        if not parent or not parent.is_active:
            raise ValueError("El departamento padre no existe o está inactivo")

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
        parent = db.get(Department, new_parent)
        if not parent or not parent.is_active:
            raise ValueError("El departamento padre no existe o está inactivo")
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


def _app_granting_position_departments(db: Session, user_id: int, app_key: str) -> list:
    """(department_id, start_date, position_id) de los puestos VIGENTES del usuario
    que otorgan acceso a ``app_key``, por rol del puesto o por permiso del puesto.

    Ordenado igual que `get_primary_user_department` para que el desempate sea el
    mismo criterio, solo que restringido a los puestos que sí anclan la app.
    """
    from sqlalchemy import or_
    from itcj2.core.models.app import App
    from itcj2.core.models.position import (
        Position, UserPosition, PositionAppRole, PositionAppPerm,
    )

    app = db.query(App).filter_by(key=app_key).first()
    if not app:
        return []

    grants_role = (
        db.query(PositionAppRole.position_id)
        .filter(PositionAppRole.app_id == app.id)
    )
    grants_perm = (
        db.query(PositionAppPerm.position_id)
        .filter(PositionAppPerm.app_id == app.id, PositionAppPerm.allow == True)  # noqa: E712
    )

    return (
        db.query(Position.department_id, UserPosition.start_date, UserPosition.position_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            _active_position_window(),
            UserPosition.user_id == user_id,
            Position.is_active == True,  # noqa: E712
            Position.department_id.isnot(None),
            or_(
                Position.id.in_(grants_role.scalar_subquery()),
                Position.id.in_(grants_perm.scalar_subquery()),
            ),
        )
        .order_by(UserPosition.start_date.asc(), UserPosition.position_id.asc())
        .all()
    )


def app_departments(db: Session, user_id: int, app_key: str) -> list:
    """Departamentos que CUENTAN para ``app_key`` — por PROCEDENCIA, con respaldo.

    Los resolvers agnósticos (`get_user_departments`) devuelven todo departamento
    con puesto vigente, sin mirar la app. Con multi-puesto eso mezcla
    departamentos ajenos: alguien con un puesto en Cafetería (que no otorga nada
    en helpdesk) y otro en Gestión podía terminar operando helpdesk "como
    Cafetería", porque el desempate por antigüedad la elegía a ella.

    Regla:
      1. Si algún puesto vigente otorga acceso a la app (rol o permiso del
         puesto), SOLO cuentan los departamentos de esos puestos.
      2. Si ninguno la otorga, el acceso viene de una asignación DIRECTA al
         usuario, que no tiene ancla departamental. Respaldo: todos sus
         departamentos. Sin esto esas personas se quedarían sin departamento y
         no podrían ni levantar un ticket.

    Mismo espíritu que `scope_service.granting_departments`, pero a nivel de APP
    (cualquier rol/permiso) en vez de un permiso concreto.
    """
    rows = _app_granting_position_departments(db, user_id, app_key)
    if not rows:
        return get_user_departments(db, user_id)

    dept_ids = {r[0] for r in rows}
    return (
        db.query(Department)
        .filter(Department.id.in_(dept_ids))
        .order_by(Department.name)
        .all()
    )


def primary_app_department(db: Session, user_id: int, app_key: str):
    """Un solo departamento para ``app_key``, con el desempate canónico.

    Para los consumidores que necesitan uno —sobre todo el sellado de
    `requester_department_id` al crear un ticket, que decide todo el scope
    posterior—. Prefiere `app_departments` cuando el scope admite varios.
    """
    rows = _app_granting_position_departments(db, user_id, app_key)
    if not rows:
        return get_primary_user_department(db, user_id)
    return db.get(Department, rows[0][0])


def build_tree(db: Session) -> list[dict]:
    """Árbol completo de departamentos ACTIVOS en 3 queries (sin N+1). Contrato C3.

    La serialización del organigrama vive AQUÍ (no en Department.to_dict, que se
    queda plano/1-nivel por compat con el drill-down clásico — spec §3.2).

    DeptNode = {id, name, code, icon, is_official, is_active, depth,
                positions_count, head: {"id", "name"} | None, children: [DeptNode]}

    - depth: 0 en raíces; un nodo cuyo parent está inactivo/ausente se trata
      como raíz (no se pierde).
    - head: usuario del puesto ``head_{code}`` con asignación VIGENTE
      (_active_position_window, no solo is_active — decisión F1b-D5).
    - Ciclos en datos corruptos: se cortan con set ``seen``; nodos de un ciclo
      sin raíz alcanzable simplemente no aparecen.
    - children ordenados por nombre (la query base ya ordena).
    """
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User

    rows = (
        db.query(Department)
        .filter(Department.is_active.is_(True))
        .order_by(Department.name)
        .all()
    )
    by_id = {d.id: d for d in rows}

    # Agregado 1: conteo de puestos activos por departamento (1 query, sin N+1)
    pos_counts = dict(
        db.query(Position.department_id, func.count(Position.id))
        .filter(Position.is_active.is_(True), Position.department_id.isnot(None))
        .group_by(Position.department_id)
        .all()
    )

    # Agregado 2: jefe por departamento (1 query). Determinista: primera
    # asignación por start_date/position_id si hubiera múltiples.
    heads: dict[int, dict] = {}
    head_rows = (
        db.query(Department.id, User)
        .select_from(Department)
        .join(Position, Position.department_id == Department.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(User, User.id == UserPosition.user_id)
        .filter(
            Department.is_active.is_(True),
            Position.code == func.concat("head_", Department.code),
            Position.is_active.is_(True),
            _active_position_window(),
        )
        .order_by(UserPosition.start_date.asc(), UserPosition.position_id.asc())
        .all()
    )
    for dept_id, head_user in head_rows:
        heads.setdefault(dept_id, {"id": head_user.id, "name": head_user.full_name})

    children_map: dict = {}
    for d in rows:
        parent_key = d.parent_id if d.parent_id in by_id else None
        children_map.setdefault(parent_key, []).append(d)

    def _node(d: Department, depth: int, seen: set) -> dict:
        kids = []
        for child in children_map.get(d.id, []):
            if child.id in seen:
                continue  # guard de ciclos
            seen.add(child.id)
            kids.append(_node(child, depth + 1, seen))
        return {
            "id": d.id,
            "name": d.name,
            "code": d.code,
            "icon": d.icon_class or "bi-building",
            "is_official": d.is_official,
            "is_active": d.is_active,
            "depth": depth,
            "positions_count": pos_counts.get(d.id, 0),
            "head": heads.get(d.id),
            "children": kids,
        }

    roots = children_map.get(None, [])
    seen = {r.id for r in roots}
    return [_node(r, 0, seen) for r in roots]
