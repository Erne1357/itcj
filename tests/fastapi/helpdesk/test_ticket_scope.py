"""Phase 5: can_user_view_ticket honra el scope por subárbol (helpdesk tickets)."""
from datetime import date, timedelta
from types import SimpleNamespace

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.ticket_service import can_user_view_ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "helpdesk.tickets.api.read.subtree"


def _helpdesk(db):
    return db.query(App).filter_by(key="helpdesk").first()


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code); db.add(p); db.commit(); db.refresh(p)
    return p


def _tk(requester_department_id, requester_id=-99, assigned=-99):
    return SimpleNamespace(requester_id=requester_id, assigned_to_user_id=assigned,
                           requester_department_id=requester_department_id)


def test_subtree_user_sees_subtree_not_other_branch(db_session):
    app = _helpdesk(db_session)
    assert app is not None
    perm = _perm(db_session, app, SUBTREE)
    b = Department(code="tks_b", name="b", is_active=True); db_session.add(b); db_session.commit(); db_session.refresh(b)
    child = Department(code="tks_bc", name="bc", parent_id=b.id, is_active=True); db_session.add(child); db_session.commit(); db_session.refresh(child)
    other = Department(code="tks_a", name="a", is_active=True); db_session.add(other); db_session.commit(); db_session.refresh(other)
    u = User(first_name="T", last_name="Tk", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    pos = Position(code="tks_pos", title="p", department_id=b.id, is_active=True, allows_multiple=True)
    db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=1), is_active=True))
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.commit()

    assert can_user_view_ticket(db_session, _tk(b.id), u.id) is True        # su depto
    assert can_user_view_ticket(db_session, _tk(child.id), u.id) is True    # sub-depto (subárbol)
    assert can_user_view_ticket(db_session, _tk(other.id), u.id) is False   # otra rama


def test_plain_user_only_own(db_session):
    u = User(first_name="P", last_name="Plain", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    d = Department(code="tks_d2", name="d2", is_active=True); db_session.add(d); db_session.commit(); db_session.refresh(d)
    assert can_user_view_ticket(db_session, _tk(d.id, requester_id=u.id), u.id) is True   # es el solicitante
    assert can_user_view_ticket(db_session, _tk(d.id), u.id) is False                     # sin scope
