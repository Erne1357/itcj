"""Phase 6: maint can_user_view_ticket honra el scope por subárbol."""
from datetime import date, timedelta
from types import SimpleNamespace

import itcj2.models  # noqa: F401
from itcj2.apps.maint.services.ticket_service import can_user_view_ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "maint.tickets.api.read.subtree"


def _maint(db):
    return db.query(App).filter_by(key="maint").first()


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code); db.add(p); db.commit(); db.refresh(p)
    return p


def _tk(requester_department_id, requester_id=-99):
    return SimpleNamespace(requester_id=requester_id, technicians=[], coordinator_id=None,
                           category=None, requester_department_id=requester_department_id)


def test_maint_subtree_visibility(db_session):
    app = _maint(db_session)
    assert app is not None, "maint app debe existir en la BD dev"
    perm = _perm(db_session, app, SUBTREE)
    b = Department(code="mts_b", name="b", is_active=True); db_session.add(b); db_session.commit(); db_session.refresh(b)
    child = Department(code="mts_bc", name="bc", parent_id=b.id, is_active=True); db_session.add(child); db_session.commit(); db_session.refresh(child)
    other = Department(code="mts_a", name="a", is_active=True); db_session.add(other); db_session.commit(); db_session.refresh(other)
    u = User(first_name="M", last_name="Mt", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    pos = Position(code="mts_pos", title="p", department_id=b.id, is_active=True, allows_multiple=True)
    db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=1), is_active=True))
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.commit()

    assert can_user_view_ticket(db_session, _tk(b.id), u.id) is True
    assert can_user_view_ticket(db_session, _tk(child.id), u.id) is True
    assert can_user_view_ticket(db_session, _tk(other.id), u.id) is False
