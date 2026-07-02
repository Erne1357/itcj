"""Phase 7: FKs BigInt, cascade de notifications, unique parcial de puestos."""
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.models.notification import Notification
from itcj2.core.models.position import Position, UserPosition

HIGH_ID = 3_000_000_000  # > 2^31, antes rompía el FK INT


def test_high_id_user_can_get_app_role(db_session):
    app = App(key="hard1", name="hard1", is_active=True); db_session.add(app); db_session.commit(); db_session.refresh(app)
    role = Role(name="hard1_role"); db_session.add(role); db_session.commit(); db_session.refresh(role)
    u = User(id=HIGH_ID, first_name="H", last_name="Id", is_active=True); db_session.add(u); db_session.commit()
    db_session.add(UserAppRole(user_id=HIGH_ID, app_id=app.id, role_id=role.id))
    db_session.commit()  # antes: "integer out of range"
    assert db_session.query(UserAppRole).filter_by(user_id=HIGH_ID, app_id=app.id).count() == 1


def test_user_deletion_cascades_notifications(db_session):
    u = User(first_name="D", last_name="Del", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    db_session.add(Notification(user_id=u.id, app_name="core", type="t", title="hola", data={}))
    db_session.commit()
    db_session.delete(u)
    db_session.commit()  # antes: ForeignKeyViolation
    assert db_session.query(Notification).filter_by(user_id=u.id).count() == 0


def test_partial_unique_allows_multiple_inactive(db_session):
    u = User(first_name="P", last_name="Pos", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    pos = Position(code="hard_pos", title="p", is_active=True); db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    # Dos filas INACTIVAS del mismo (user, position): antes rompía el unique de 3 cols.
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=10),
                                end_date=date.today() - timedelta(days=5), is_active=False))
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=4),
                                end_date=date.today() - timedelta(days=1), is_active=False))
    db_session.commit()  # OK con el índice parcial (solo únicos WHERE is_active)
    assert db_session.query(UserPosition).filter_by(user_id=u.id, position_id=pos.id, is_active=False).count() == 2


def test_partial_unique_blocks_two_active(db_session):
    u = User(first_name="P2", last_name="Pos2", is_active=True); db_session.add(u); db_session.commit(); db_session.refresh(u)
    pos = Position(code="hard_pos2", title="p", is_active=True); db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today(), is_active=True))
    db_session.commit()
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today(), is_active=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
