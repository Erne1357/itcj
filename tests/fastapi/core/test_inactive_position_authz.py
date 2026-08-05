"""Un puesto dado de baja deja de otorgar roles y permisos.

`update_position(is_active=False)` es lo que la UI de config llama "desactivar
puesto": marca el flag y bustea el caché, pero no cierra las asignaciones. Si la
resolución de authz solo mira la vigencia de la ASIGNACIÓN y nunca la del PUESTO,
el titular conserva rol y permisos indefinidamente.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.core.services.authz_service import (
    effective_perm_set, user_roles_in_app, user_perms_via_positions_direct,
    user_perms_via_position_roles, user_roles_via_positions,
)
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm

DIRECT_PERM = "helpdesk.tickets.api.read.own"
ROLE_PERM = "helpdesk.tickets.api.create"


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p); db.commit(); db.refresh(p)
    return p


def _setup(db, *, position_active: bool):
    app = db.query(App).filter_by(key="helpdesk").first()
    direct = _perm(db, app, DIRECT_PERM)
    via = _perm(db, app, ROLE_PERM)

    role = db.query(Role).filter_by(name="ipa_role").first()
    if not role:
        role = Role(name="ipa_role"); db.add(role); db.commit(); db.refresh(role)
    if not db.query(RolePermission).filter_by(role_id=role.id, perm_id=via.id).first():
        db.add(RolePermission(role_id=role.id, perm_id=via.id)); db.commit()

    d = Department(code="ipa_dept", name="ipa", is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    u = User(first_name="I", last_name="Pos", is_active=True)
    db.add(u); db.commit(); db.refresh(u)

    pos = Position(code="ipa_pos", title="Puesto", department_id=d.id,
                   is_active=position_active, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=u.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=direct.id, allow=True))
    db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db.commit()
    return u


def test_active_position_grants_role_and_perms(db_session):
    """Control: con el puesto vigente, el titular recibe rol y permisos."""
    u = _setup(db_session, position_active=True)

    assert "ipa_role" in user_roles_in_app(db_session, u.id, "helpdesk")
    perms = effective_perm_set(db_session, u.id, "helpdesk")
    assert {DIRECT_PERM, ROLE_PERM} <= perms


def test_inactive_position_grants_nothing(db_session):
    """Puesto desactivado → sin rol y sin permisos, por las dos vías."""
    u = _setup(db_session, position_active=False)

    assert user_roles_via_positions(db_session, u.id, "helpdesk") == set()
    assert user_perms_via_positions_direct(db_session, u.id, "helpdesk") == set()
    assert user_perms_via_position_roles(db_session, u.id, "helpdesk") == set()
    assert "ipa_role" not in user_roles_in_app(db_session, u.id, "helpdesk")
    assert effective_perm_set(db_session, u.id, "helpdesk") == set()
