"""Task 3.2: resolve_read_scope — 5 ramas de precedencia (all/set/own/none)."""
from datetime import date, timedelta
from unittest.mock import patch

from itcj2.core.services import scope_service as ss
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

YEST = date.today() - timedelta(days=1)
ALL = "res.read.all"
SUB = "res.read.subtree"
DEPT = "res.read.own_dept"
OWN = "res.read.own"


def _fixt(db, key):
    app = App(key=key, name=key, is_active=True); db.add(app); db.commit(); db.refresh(app)
    for code in (ALL, SUB, DEPT, OWN):
        db.add(Permission(app_id=app.id, code=code, name=code))
    db.commit()
    u = User(first_name="R", last_name="Res", is_active=True); db.add(u); db.commit(); db.refresh(u)
    return app, u


def _pos_granting(db, app, u, code, dept_id):
    p = Position(code=f"{app.key}_p", title="p", department_id=dept_id, is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p)
    db.add(UserPosition(user_id=u.id, position_id=p.id, start_date=YEST, is_active=True))
    perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    db.add(PositionAppPerm(position_id=p.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def test_global_admin_all(db_session):
    app, u = _fixt(db_session, "res1")
    r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "admin"}, app.key,
                              all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "all"


def test_all_perm(db_session):
    app, u = _fixt(db_session, "res2")
    with patch("itcj2.core.services.authz_cache.cached_perms", return_value={ALL}):
        r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "x"}, app.key,
                                  all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "all"


def test_subtree_set(db_session):
    app, u = _fixt(db_session, "res3")
    b = Department(code="res3_b", name="b", is_active=True); db_session.add(b); db_session.commit(); db_session.refresh(b)
    child = Department(code="res3_bc", name="bc", parent_id=b.id, is_active=True); db_session.add(child); db_session.commit(); db_session.refresh(child)
    _pos_granting(db_session, app, u, SUB, b.id)
    with patch("itcj2.core.services.authz_cache.cached_perms", return_value={SUB}):
        r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "x"}, app.key,
                                  all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "set"
    assert r.department_ids == frozenset({b.id, child.id})  # subtree incluye descendiente


def test_dept_perm_exact_no_descendants(db_session):
    app, u = _fixt(db_session, "res4")
    b = Department(code="res4_b", name="b", is_active=True); db_session.add(b); db_session.commit(); db_session.refresh(b)
    child = Department(code="res4_bc", name="bc", parent_id=b.id, is_active=True); db_session.add(child); db_session.commit(); db_session.refresh(child)
    _pos_granting(db_session, app, u, DEPT, b.id)
    with patch("itcj2.core.services.authz_cache.cached_perms", return_value={DEPT}):
        r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "x"}, app.key,
                                  all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "set"
    assert r.department_ids == frozenset({b.id})  # exacto, SIN descendiente


def test_own(db_session):
    app, u = _fixt(db_session, "res5")
    with patch("itcj2.core.services.authz_cache.cached_perms", return_value={OWN}):
        r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "x"}, app.key,
                                  all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "own"


def test_none(db_session):
    app, u = _fixt(db_session, "res6")
    with patch("itcj2.core.services.authz_cache.cached_perms", return_value=set()):
        r = ss.resolve_read_scope(db_session, {"sub": str(u.id), "role": "x"}, app.key,
                                  all_perm=ALL, subtree_perm=SUB, dept_perm=DEPT, own_perm=OWN)
    assert r.kind == "none"
