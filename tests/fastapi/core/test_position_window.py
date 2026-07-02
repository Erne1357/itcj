"""Task 2.2: puestos con end_date pasado o start_date futuro NO otorgan acceso."""
from datetime import date, timedelta

from itcj2.core.services import authz_service as az
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppRole


def _setup(db, key, start, end):
    app = App(key=key, name=key, is_active=True); db.add(app); db.commit(); db.refresh(app)
    role = Role(name=f"{key}_r"); db.add(role); db.commit(); db.refresh(role)
    perm = Permission(app_id=app.id, code=f"{key}.p", name="p"); db.add(perm); db.commit(); db.refresh(perm)
    db.add(RolePermission(role_id=role.id, perm_id=perm.id)); db.commit()
    pos = Position(code=f"{key}_pos", title="p", is_active=True); db.add(pos); db.commit(); db.refresh(pos)
    db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id)); db.commit()
    u = User(first_name="W", last_name="Win", is_active=True); db.add(u); db.commit(); db.refresh(u)
    db.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=start, end_date=end, is_active=True)); db.commit()
    return app, role, u


def test_expired_position_grants_nothing(db_session):
    app, role, u = _setup(db_session, "pw1", date.today() - timedelta(days=100), date.today() - timedelta(days=1))
    assert role.name not in az.user_roles_in_app(db_session, u.id, app.key)
    assert az.effective_perms(db_session, u.id, app.key)["effective"] == []
    assert az.has_any_assignment(db_session, u.id, app.key) is False


def test_future_position_grants_nothing(db_session):
    app, role, u = _setup(db_session, "pw2", date.today() + timedelta(days=5), None)
    assert role.name not in az.user_roles_in_app(db_session, u.id, app.key)
    assert az.has_any_assignment(db_session, u.id, app.key) is False


def test_current_position_grants(db_session):
    app, role, u = _setup(db_session, "pw3", date.today() - timedelta(days=1), None)
    assert role.name in az.user_roles_in_app(db_session, u.id, app.key)
    assert az.has_any_assignment(db_session, u.id, app.key) is True
