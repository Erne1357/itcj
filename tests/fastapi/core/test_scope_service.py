"""Task 3.1: scope por PROCEDENCIA — subtree de los puestos que otorgan el perm."""
from datetime import date, timedelta

from itcj2.core.services import scope_service as ss
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm

TODAY = date.today()
YEST = TODAY - timedelta(days=1)


def _app(db, key):
    a = App(key=key, name=key, is_active=True); db.add(a); db.commit(); db.refresh(a); return a


def _dept(db, code, parent=None):
    d = Department(code=code, name=code, parent_id=parent, is_active=True); db.add(d); db.commit(); db.refresh(d); return d


def _perm(db, app, code):
    p = Permission(app_id=app.id, code=code, name=code); db.add(p); db.commit(); db.refresh(p); return p


def _user(db):
    u = User(first_name="S", last_name="Scope", is_active=True); db.add(u); db.commit(); db.refresh(u); return u


def _pos(db, code, dept_id):
    p = Position(code=code, title=code, department_id=dept_id, is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p); return p


def _assign(db, uid, pid):
    db.add(UserPosition(user_id=uid, position_id=pid, start_date=YEST, is_active=True)); db.commit()


def _pos_perm(db, pid, app, perm):
    db.add(PositionAppPerm(position_id=pid, app_id=app.id, perm_id=perm.id, allow=True)); db.commit()


def _pos_role(db, pid, app, role):
    db.add(PositionAppRole(position_id=pid, app_id=app.id, role_id=role.id)); db.commit()


def test_maestra_plus_secretaria_only_secretaria_dept(db_session):
    app = _app(db_session, "sc1")
    perm = _perm(db_session, app, "sc1.read.subtree")
    a = _dept(db_session, "sc1_academico")           # dept maestra
    b = _dept(db_session, "sc1_admin")               # dept secretaria
    b_child = _dept(db_session, "sc1_admin_sub", parent=b.id)
    u = _user(db_session)
    p_maestra = _pos(db_session, "sc1_maestra", a.id)
    p_secre = _pos(db_session, "sc1_secre", b.id)
    _assign(db_session, u.id, p_maestra.id)
    _assign(db_session, u.id, p_secre.id)
    # SOLO la secretaria otorga read.subtree (por perm directo del puesto)
    _pos_perm(db_session, p_secre.id, app, perm)
    scope = ss.subtree_scope_for(db_session, u.id, app.key, "sc1.read.subtree")
    assert scope == {b.id, b_child.id}    # subtree(B) — incluye descendiente
    assert a.id not in scope              # NO ve el dept donde es maestra


def test_secretaria_de_tres_deptos_union(db_session):
    app = _app(db_session, "sc2")
    perm = _perm(db_session, app, "sc2.read.subtree")
    b1 = _dept(db_session, "sc2_b1"); b2 = _dept(db_session, "sc2_b2"); b3 = _dept(db_session, "sc2_b3")
    u = _user(db_session)
    for i, b in enumerate((b1, b2, b3)):
        p = _pos(db_session, f"sc2_secre{i}", b.id)
        _assign(db_session, u.id, p.id)
        _pos_perm(db_session, p.id, app, perm)
    scope = ss.subtree_scope_for(db_session, u.id, app.key, "sc2.read.subtree")
    assert scope == {b1.id, b2.id, b3.id}


def test_direct_grant_no_anchor(db_session):
    app = _app(db_session, "sc3")
    perm = _perm(db_session, app, "sc3.read.subtree")
    u = _user(db_session)
    # Grant DIRECTO al usuario (sin puesto) → sin ancla de depto
    db_session.add(UserAppPerm(user_id=u.id, app_id=app.id, perm_id=perm.id, allow=True)); db_session.commit()
    assert ss.granting_departments(db_session, u.id, app.key, "sc3.read.subtree") == set()
    assert ss.subtree_scope_for(db_session, u.id, app.key, "sc3.read.subtree") == set()


def test_role_path_counted(db_session):
    app = _app(db_session, "sc4")
    perm = _perm(db_session, app, "sc4.read.subtree")
    role = Role(name="sc4_role"); db_session.add(role); db_session.commit(); db_session.refresh(role)
    db_session.add(RolePermission(role_id=role.id, perm_id=perm.id)); db_session.commit()
    b = _dept(db_session, "sc4_b")
    u = _user(db_session)
    p = _pos(db_session, "sc4_pos", b.id)
    _assign(db_session, u.id, p.id)
    _pos_role(db_session, p.id, app, role)   # el perm llega por ROL del puesto
    assert ss.granting_departments(db_session, u.id, app.key, "sc4.read.subtree") == {b.id}
