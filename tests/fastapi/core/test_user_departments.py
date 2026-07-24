"""Task 1.4: resolver canónico de departamento(s) por usuario (multi-puesto)."""
from datetime import date, timedelta

from itcj2.core.services import departments_service as ds
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition


def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d); return d


def _user(db, first="T", last="User"):
    u = User(first_name=first, last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u); return u


def _pos(db, code, dept_id):
    p = Position(code=code, title=code, department_id=dept_id, is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p); return p


def _assign(db, user_id, pos_id, start, end=None, active=True):
    up = UserPosition(user_id=user_id, position_id=pos_id, start_date=start, end_date=end, is_active=active)
    db.add(up); db.commit(); db.refresh(up); return up


def test_multi_position_returns_all(db_session):
    a = _dept(db_session, "ud_A"); b = _dept(db_session, "ud_B")
    u = _user(db_session)
    pa = _pos(db_session, "ud_pa", a.id); pb = _pos(db_session, "ud_pb", b.id)
    _assign(db_session, u.id, pa.id, date.today() - timedelta(days=10))
    _assign(db_session, u.id, pb.id, date.today() - timedelta(days=5))
    depts = ds.get_user_departments(db_session, u.id)
    ids = {d.id for d in depts}
    assert ids == {a.id, b.id}


def test_primary_is_earliest_start_deterministic(db_session):
    a = _dept(db_session, "ud_A2"); b = _dept(db_session, "ud_B2")
    u = _user(db_session)
    pa = _pos(db_session, "ud_pa2", a.id); pb = _pos(db_session, "ud_pb2", b.id)
    _assign(db_session, u.id, pa.id, date.today() - timedelta(days=3))   # más nuevo
    _assign(db_session, u.id, pb.id, date.today() - timedelta(days=30))  # más viejo
    primary = ds.get_primary_user_department(db_session, u.id)
    assert primary.id == b.id  # earliest start


def test_expired_position_excluded(db_session):
    a = _dept(db_session, "ud_A3")
    u = _user(db_session)
    pa = _pos(db_session, "ud_pa3", a.id)
    _assign(db_session, u.id, pa.id, date.today() - timedelta(days=100),
            end=date.today() - timedelta(days=1))  # venció ayer
    assert ds.get_user_departments(db_session, u.id) == []


def test_future_start_excluded(db_session):
    a = _dept(db_session, "ud_A4")
    u = _user(db_session)
    pa = _pos(db_session, "ud_pa4", a.id)
    _assign(db_session, u.id, pa.id, date.today() + timedelta(days=5))  # empieza en el futuro
    assert ds.get_user_departments(db_session, u.id) == []


def test_get_user_department_delegates_to_primary(db_session):
    a = _dept(db_session, "ud_A5"); b = _dept(db_session, "ud_B5")
    u = _user(db_session)
    pa = _pos(db_session, "ud_pa5", a.id); pb = _pos(db_session, "ud_pb5", b.id)
    _assign(db_session, u.id, pa.id, date.today() - timedelta(days=2))
    _assign(db_session, u.id, pb.id, date.today() - timedelta(days=40))
    assert ds.get_user_department(db_session, u.id).id == b.id
