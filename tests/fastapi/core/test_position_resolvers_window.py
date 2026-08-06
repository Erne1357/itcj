"""Los resolvers puesto→usuario/departamento deben respetar la vigencia.

`departments_service._active_position_window()` es el filtro canónico (activo y
dentro de [start_date, end_date]). Varios resolvers seguían con el patrón viejo
`is_active == True` a secas, que deja pasar asignaciones vencidas o con inicio
futuro, y sin `ORDER BY`, así que el "primario" era el que Postgres devolviera.

`get_user_managed_departments` importa especialmente: alimenta el dashboard del
jefe de helpdesk, y de ahí sale la raíz del subárbol y del scope de la lista.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.warehouse.services.utils import get_user_dept_code
from itcj2.core.services.positions_service import (
    get_position_current_users, get_user_active_positions,
    get_user_managed_departments, get_user_primary_managed_department,
)
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition

TODAY = date.today()


def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="W", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _head_position(db, code, department):
    p = Position(code=code, title=code, department_id=department.id,
                 is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _assign(db, user, position, start_date, end_date=None):
    db.add(UserPosition(user_id=user.id, position_id=position.id,
                        start_date=start_date, end_date=end_date, is_active=True))
    db.commit()


def test_expired_assignment_does_not_manage_department(db_session):
    """Jefatura con `end_date` pasado pero `is_active` aún en true."""
    d = _dept(db_session, "prw_expired")
    u = _user(db_session, "Expired")
    pos = _head_position(db_session, "head_prw_expired", d)
    _assign(db_session, u, pos, TODAY - timedelta(days=30), end_date=TODAY - timedelta(days=1))

    assert get_user_managed_departments(db_session, u.id) == []
    assert get_user_primary_managed_department(db_session, u.id) is None


def test_future_assignment_does_not_manage_department_yet(db_session):
    d = _dept(db_session, "prw_future")
    u = _user(db_session, "Future")
    pos = _head_position(db_session, "head_prw_future", d)
    _assign(db_session, u, pos, TODAY + timedelta(days=10))

    assert get_user_managed_departments(db_session, u.id) == []


def test_primary_managed_department_is_deterministic(db_session):
    """Con dos jefaturas vigentes, la primaria es la más antigua — siempre la misma."""
    older = _dept(db_session, "prw_older")
    newer = _dept(db_session, "prw_newer")
    u = _user(db_session, "Multi")
    _assign(db_session, u, _head_position(db_session, "head_prw_older", older),
            TODAY - timedelta(days=100))
    _assign(db_session, u, _head_position(db_session, "head_prw_newer", newer),
            TODAY - timedelta(days=10))

    for _ in range(3):
        primary = get_user_primary_managed_department(db_session, u.id)
        assert primary["department"]["code"] == "prw_older"


def test_expired_assignment_hidden_from_position_resolvers(db_session):
    d = _dept(db_session, "prw_res")
    u = _user(db_session, "Res")
    pos = _head_position(db_session, "head_prw_res", d)
    _assign(db_session, u, pos, TODAY - timedelta(days=30), end_date=TODAY - timedelta(days=1))

    assert get_user_active_positions(db_session, u.id) == []
    assert get_position_current_users(db_session, pos.id) == []


def test_warehouse_dept_code_ignores_expired_position(db_session):
    """El almacén acota por `department_code`: un puesto vencido no puede conservarlo."""
    d = _dept(db_session, "prw_wh")
    u = _user(db_session, "Wh")
    pos = _head_position(db_session, "head_prw_wh", d)
    _assign(db_session, u, pos, TODAY - timedelta(days=30), end_date=TODAY - timedelta(days=1))

    assert get_user_dept_code(db_session, u.id) is None
