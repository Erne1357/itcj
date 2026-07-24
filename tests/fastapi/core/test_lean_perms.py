"""Polish: effective_perm_set (lean) == get_user_permissions_for_app, sin computar roles."""
from datetime import date, timedelta
from unittest.mock import patch

from itcj2.core.services import authz_service as az
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.position import Position, UserPosition, PositionAppRole


def _setup(db, key):
    app = App(key=key, name=key, is_active=True); db.add(app); db.commit(); db.refresh(app)
    role = Role(name=f"{key}_role"); db.add(role); db.commit(); db.refresh(role)
    # perm por rol, perm directo, y un perm denegado
    p_role = Permission(app_id=app.id, code=f"{key}.viarole", name="r")
    p_direct = Permission(app_id=app.id, code=f"{key}.direct", name="d")
    p_deny = Permission(app_id=app.id, code=f"{key}.deny", name="x")
    db.add_all([p_role, p_direct, p_deny]); db.commit()
    db.add(RolePermission(role_id=role.id, perm_id=p_role.id))
    db.add(RolePermission(role_id=role.id, perm_id=p_deny.id))  # otorgado por rol...
    db.commit()
    u = User(first_name="L", last_name="Lean", is_active=True); db.add(u); db.commit(); db.refresh(u)
    # rol vía puesto
    pos = Position(code=f"{key}_pos", title="p", is_active=True); db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today()-timedelta(days=1), is_active=True))
    db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    # perm directo + deny directo
    db.add(UserAppPerm(user_id=u.id, app_id=app.id, perm_id=p_direct.id, allow=True))
    db.add(UserAppPerm(user_id=u.id, app_id=app.id, perm_id=p_deny.id, allow=False))  # ...pero denegado
    db.commit()
    return app, u


def test_lean_equals_full(db_session):
    app, u = _setup(db_session, "lean1")
    full = az.get_user_permissions_for_app(db_session, u.id, app.key)
    lean = az.effective_perm_set(db_session, u.id, app.key)
    assert lean == full
    assert "lean1.viarole" in lean and "lean1.direct" in lean
    assert "lean1.deny" not in lean          # deny gana


def test_lean_does_not_compute_roles(db_session):
    app, u = _setup(db_session, "lean2")
    with patch("itcj2.core.services.authz_service.user_roles_in_app") as mock_roles:
        az.effective_perm_set(db_session, u.id, app.key)
    mock_roles.assert_not_called()           # el hot path no calcula el set de roles
