"""Task 3.4: avisar al asignar un perm .subtree directo a un usuario sin puesto."""
from datetime import date, timedelta

from itcj2.core.api import authz as authz_api
from itcj2.core.api.authz import UserPermBody
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm


def _fixt(db, key):
    app = App(key=key, name=key, is_active=True); db.add(app); db.commit(); db.refresh(app)
    perm = Permission(app_id=app.id, code=f"{key}.tickets.api.read.subtree", name="s")
    db.add(perm); db.commit(); db.refresh(perm)
    u = User(first_name="G", last_name="Guard", is_active=True); db.add(u); db.commit(); db.refresh(u)
    return app, perm, u


def test_direct_subtree_grant_warns(db_session):
    app, perm, u = _fixt(db_session, "grd1")
    body = UserPermBody(code=perm.code, allow=True)
    resp = authz_api.add_user_perm(app_key=app.key, user_id=u.id, body=body,
                                   user={"sub": "1"}, db=db_session)
    assert resp.get("warning") == "scope_departamental_sin_puesto"


def test_subtree_grant_with_backing_position_no_warning(db_session):
    app, perm, u = _fixt(db_session, "grd2")
    from itcj2.core.models.department import Department
    d = Department(code="grd2_d", name="d", is_active=True); db_session.add(d); db_session.commit(); db_session.refresh(d)
    pos = Position(code="grd2_pos", title="p", department_id=d.id, is_active=True); db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=1), is_active=True))
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.commit()
    body = UserPermBody(code=perm.code, allow=True)
    resp = authz_api.add_user_perm(app_key=app.key, user_id=u.id, body=body,
                                   user={"sub": "1"}, db=db_session)
    assert "warning" not in resp


def test_non_subtree_grant_no_warning(db_session):
    app, _, u = _fixt(db_session, "grd3")
    p2 = Permission(app_id=app.id, code="grd3.tickets.api.read.all", name="all")
    db_session.add(p2); db_session.commit()
    body = UserPermBody(code="grd3.tickets.api.read.all", allow=True)
    resp = authz_api.add_user_perm(app_key=app.key, user_id=u.id, body=body,
                                   user={"sub": "1"}, db=db_session)
    assert "warning" not in resp
