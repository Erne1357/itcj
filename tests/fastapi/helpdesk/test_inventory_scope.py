"""Phase 4: visible_department_ids — scope de inventario helpdesk (aditivo + subtree)."""
from datetime import date, timedelta

import itcj2.models  # noqa: F401  (mappers)
from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "helpdesk.inventory.api.read.subtree"


def _helpdesk(db):
    return db.query(App).filter_by(key="helpdesk").first()


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p); db.commit(); db.refresh(p)
    return p


def _user(db):
    u = User(first_name="I", last_name="Inv", is_active=True); db.add(u); db.commit(); db.refresh(u); return u


def test_global_admin_sees_all(db_session):
    u = _user(db_session)
    assert visible_department_ids(db_session, {"sub": str(u.id), "role": "admin"}) is None


def test_no_grants_sees_nothing(db_session):
    u = _user(db_session)
    assert visible_department_ids(db_session, {"sub": str(u.id), "role": "staff"}) == set()


def test_subtree_via_position(db_session):
    app = _helpdesk(db_session)
    assert app is not None, "helpdesk app debe existir en la BD dev"
    perm = _perm(db_session, app, SUBTREE)
    b = Department(code="invsc_b", name="b", is_active=True); db_session.add(b); db_session.commit(); db_session.refresh(b)
    child = Department(code="invsc_bc", name="bc", parent_id=b.id, is_active=True); db_session.add(child); db_session.commit(); db_session.refresh(child)
    u = _user(db_session)
    pos = Position(code="invsc_pos", title="p", department_id=b.id, is_active=True, allows_multiple=True)
    db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=1), is_active=True))
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.commit()
    ids = visible_department_ids(db_session, {"sub": str(u.id), "role": "department_head"})
    assert ids == {b.id, child.id}  # subtree incluye el sub-departamento
