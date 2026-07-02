"""Polish: activate_period valida antes del bulk; notification_service commitea."""
from datetime import date

import pytest

from itcj2.core.services import period_service as ps
from itcj2.core.services.notification_service import NotificationService
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.user import User
from itcj2.core.models.notification import Notification


def _period(db, code, status):
    p = AcademicPeriod(code=code, name=f"Periodo {code}", start_date=date(2026, 1, 1),
                       end_date=date(2026, 6, 30), status=status)
    db.add(p); db.commit(); db.refresh(p); return p


def test_activate_invalid_keeps_existing_active(db_session):
    active = _period(db_session, "AP9001", "ACTIVE")
    with pytest.raises(ValueError):
        ps.activate_period(db_session, 99999999)   # id inexistente
    db_session.refresh(active)
    assert active.status == "ACTIVE"               # NO se desactivó todo


def test_activate_valid_switches(db_session):
    old = _period(db_session, "AP9002", "ACTIVE")
    new = _period(db_session, "AP9003", "INACTIVE")
    ps.activate_period(db_session, new.id)
    db_session.refresh(old); db_session.refresh(new)
    assert new.status == "ACTIVE" and old.status == "INACTIVE"


def test_mark_read_commits_in_service(db_session):
    u = User(first_name="N", last_name="Notif", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    n = Notification(user_id=u.id, app_name="core", type="t", title="hola", data={}, is_read=False)
    db_session.add(n); db_session.commit(); db_session.refresh(n)
    # El service commitea internamente (sin commit del endpoint).
    assert NotificationService.mark_read(db_session, n.id, u.id) is True
    db_session.expire(n)
    assert db_session.get(Notification, n.id).is_read is True
