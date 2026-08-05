"""`users_with_assignment_select` — gemelo en conjunto de `has_any_assignment`.

Semántica SQL pura (UNION de 4 vías + ventana de vigencia del puesto), así que
va contra Postgres real: con mocks no se puede comprobar a QUIÉN deja pasar.

Origen: el picker "Solicitar para" de maint listaba alumnos —usuarios sin puesto
ni rol en la app— porque filtraba solo por `User.is_active`.
"""
from datetime import date, timedelta

from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import (
    Position, PositionAppPerm, PositionAppRole, UserPosition,
)
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.services.authz_service import (
    has_any_assignment, users_with_assignment_select,
)

TODAY = date.today()
YEST = TODAY - timedelta(days=1)


def _app(db, key):
    a = App(key=key, name=key, is_active=True); db.add(a); db.commit(); db.refresh(a); return a


def _user(db, name):
    u = User(first_name=name, last_name="Elig", is_active=True)
    db.add(u); db.commit(); db.refresh(u); return u


def _pos(db, code, dept_id=None):
    p = Position(code=code, title=code, department_id=dept_id, is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p); return p


def _assign(db, uid, pid, start=YEST, end=None):
    db.add(UserPosition(user_id=uid, position_id=pid, start_date=start, end_date=end, is_active=True))
    db.commit()


def _role(db, name):
    r = Role(name=name); db.add(r); db.commit(); db.refresh(r); return r


def _eligible_ids(db, app_key):
    return {row[0] for row in db.execute(users_with_assignment_select(db, app_key)).fetchall()}


def test_student_without_position_or_role_is_excluded(db_session):
    """El caso del bug: alumno activo, sin puesto y sin rol en la app."""
    app = _app(db_session, "elig1")
    student = _user(db_session, "Alumno")
    assert student.id not in _eligible_ids(db_session, "elig1")
    assert has_any_assignment(db_session, student.id, "elig1") is False


def test_direct_user_role_is_included(db_session):
    app = _app(db_session, "elig2")
    role = _role(db_session, "elig2_role")
    u = _user(db_session, "RolDirecto")
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id)); db_session.commit()
    assert u.id in _eligible_ids(db_session, "elig2")


def test_direct_user_perm_is_included_and_deny_is_not(db_session):
    """`allow=False` es una DENEGACIÓN, no una asignación."""
    app = _app(db_session, "elig3")
    perm = Permission(app_id=app.id, code="elig3.x", name="x")
    db_session.add(perm); db_session.commit(); db_session.refresh(perm)
    allowed = _user(db_session, "PermAllow")
    denied = _user(db_session, "PermDeny")
    db_session.add(UserAppPerm(user_id=allowed.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.add(UserAppPerm(user_id=denied.id, app_id=app.id, perm_id=perm.id, allow=False))
    db_session.commit()

    ids = _eligible_ids(db_session, "elig3")
    assert allowed.id in ids
    assert denied.id not in ids


def test_role_inherited_from_active_position_is_included(db_session):
    """Jefes y secretarias entran a maint por PUESTO, no por core_user_app_roles."""
    app = _app(db_session, "elig4")
    role = _role(db_session, "elig4_role")
    dept = Department(code="elig4_dept", name="elig4_dept", is_active=True)
    db_session.add(dept); db_session.commit(); db_session.refresh(dept)
    u = _user(db_session, "Jefe")
    pos = _pos(db_session, "elig4_head", dept.id)
    _assign(db_session, u.id, pos.id)
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id)); db_session.commit()

    assert u.id in _eligible_ids(db_session, "elig4")


def test_perm_inherited_from_active_position_is_included(db_session):
    app = _app(db_session, "elig5")
    perm = Permission(app_id=app.id, code="elig5.x", name="x")
    db_session.add(perm); db_session.commit(); db_session.refresh(perm)
    u = _user(db_session, "Secre")
    pos = _pos(db_session, "elig5_secre")
    _assign(db_session, u.id, pos.id)
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.commit()

    assert u.id in _eligible_ids(db_session, "elig5")


def test_expired_position_is_excluded(db_session):
    """Puesto con end_date pasada: ya no da acceso (misma ventana que require_app)."""
    app = _app(db_session, "elig6")
    role = _role(db_session, "elig6_role")
    u = _user(db_session, "ExJefe")
    pos = _pos(db_session, "elig6_head")
    _assign(db_session, u.id, pos.id, start=TODAY - timedelta(days=30), end=TODAY - timedelta(days=1))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id)); db_session.commit()

    assert u.id not in _eligible_ids(db_session, "elig6")
    assert has_any_assignment(db_session, u.id, "elig6") is False


def test_assignment_in_another_app_does_not_leak(db_session):
    """Tener rol en otra app no habilita a aparecer en el picker de esta."""
    app_a = _app(db_session, "elig7a")
    _app(db_session, "elig7b")
    role = _role(db_session, "elig7_role")
    u = _user(db_session, "OtraApp")
    db_session.add(UserAppRole(user_id=u.id, app_id=app_a.id, role_id=role.id)); db_session.commit()

    assert u.id in _eligible_ids(db_session, "elig7a")
    assert u.id not in _eligible_ids(db_session, "elig7b")


def test_matches_has_any_assignment_for_every_user(db_session):
    """La versión de conjunto y la de un usuario no pueden divergir."""
    app = _app(db_session, "elig8")
    role = _role(db_session, "elig8_role")
    with_role = _user(db_session, "Con")
    without = _user(db_session, "Sin")
    expired = _user(db_session, "Vencido")
    pos = _pos(db_session, "elig8_pos")
    _assign(db_session, expired.id, pos.id, start=TODAY - timedelta(days=10), end=TODAY - timedelta(days=2))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db_session.add(UserAppRole(user_id=with_role.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    ids = _eligible_ids(db_session, "elig8")
    for u in (with_role, without, expired):
        assert (u.id in ids) is has_any_assignment(db_session, u.id, "elig8"), u.first_name
