"""Task 2.1: allow=False (deny) debe REMOVER un permiso, incluso si viene por rol."""
from datetime import date, timedelta

from itcj2.core.services import authz_service as az
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm


def _base(db, key):
    app = App(key=key, name=key, is_active=True)
    db.add(app); db.commit(); db.refresh(app)
    role = Role(name=f"{key}_role"); db.add(role); db.commit(); db.refresh(role)
    perm = Permission(app_id=app.id, code=f"{key}.x", name="x")
    db.add(perm); db.commit(); db.refresh(perm)
    db.add(RolePermission(role_id=role.id, perm_id=perm.id)); db.commit()
    u = User(first_name="D", last_name="Deny", is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return app, role, perm, u


def test_user_deny_removes_role_granted_perm(db_session):
    app, role, perm, u = _base(db_session, "dz1")
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id)); db_session.commit()
    eff = set(az.effective_perms(db_session, u.id, app.key)["effective"])
    assert "dz1.x" in eff  # otorgado por rol
    db_session.add(UserAppPerm(user_id=u.id, app_id=app.id, perm_id=perm.id, allow=False)); db_session.commit()
    eff2 = set(az.effective_perms(db_session, u.id, app.key)["effective"])
    assert "dz1.x" not in eff2  # deny gana


def test_position_deny_removes_role_granted_perm(db_session):
    app, role, perm, u = _base(db_session, "dz2")
    pos = Position(code="dz2_pos", title="p", is_active=True); db_session.add(pos); db_session.commit(); db_session.refresh(pos)
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today() - timedelta(days=1), is_active=True))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id)); db_session.commit()
    eff = set(az.effective_perms(db_session, u.id, app.key)["effective"])
    assert "dz2.x" in eff
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=False)); db_session.commit()
    eff2 = set(az.effective_perms(db_session, u.id, app.key)["effective"])
    assert "dz2.x" not in eff2


def test_allow_only_user_unaffected(db_session):
    app, role, perm, u = _base(db_session, "dz3")
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id)); db_session.commit()
    eff = set(az.effective_perms(db_session, u.id, app.key)["effective"])
    assert "dz3.x" in eff  # sin deny, no cambia (regresión)
