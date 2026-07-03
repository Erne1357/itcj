"""F1a (C3): servicios batch anti-429 — procedencia espejo de has_any_assignment."""
from datetime import date, timedelta

from itcj2.core.services import authz_service as az
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppRole, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.user_app_role import UserAppRole


def _seed(db):
    """2 apps activas + 1 inactiva; u: rol directo en ba1 (rol otorga p1) y perm
    directo p2 en ba2; v: sin nada."""
    a1 = App(key="ba1", name="ba1", is_active=True)
    a2 = App(key="ba2", name="ba2", is_active=True)
    a3 = App(key="ba3", name="ba3", is_active=False)
    db.add_all([a1, a2, a3]); db.commit()
    role = Role(name="ba_role"); db.add(role); db.commit()
    p1 = Permission(app_id=a1.id, code="ba1.x.api.read", name="x")
    p2 = Permission(app_id=a2.id, code="ba2.y.api.read", name="y")
    db.add_all([p1, p2]); db.commit()
    db.add(RolePermission(role_id=role.id, perm_id=p1.id)); db.commit()
    u = User(first_name="B", last_name="Batch", is_active=True)
    v = User(first_name="N", last_name="Nada", is_active=True)
    db.add_all([u, v]); db.commit()
    db.add(UserAppRole(user_id=u.id, app_id=a1.id, role_id=role.id))
    db.add(UserAppPerm(user_id=u.id, app_id=a2.id, perm_id=p2.id, allow=True))
    db.commit()
    return a1, a2, a3, role, p1, p2, u, v


def test_assignments_map_shape_and_content(db_session):
    a1, a2, a3, role, p1, p2, u, v = _seed(db_session)
    m = az.user_app_assignments_map(db_session, u.id)
    assert m["ba1"]["roles"] == ["ba_role"]
    assert m["ba1"]["perms"] == []
    assert m["ba1"]["effective"] == ["ba1.x.api.read"]
    assert m["ba2"]["roles"] == []
    assert m["ba2"]["perms"] == ["ba2.y.api.read"]
    assert m["ba2"]["effective"] == ["ba2.y.api.read"]
    assert "ba3" not in m  # apps inactivas fuera
    # shape C3 en TODAS las llaves (incluye apps reales del seed dev)
    for entry in m.values():
        assert set(entry.keys()) == {"roles", "perms", "effective"}


def test_assignments_map_includes_position_grants(db_session):
    a1, a2, a3, role, p1, p2, u, v = _seed(db_session)
    pos = Position(code="ba_pos", title="p", is_active=True)
    db_session.add(pos); db_session.commit()
    db_session.add(PositionAppRole(position_id=pos.id, app_id=a1.id, role_id=role.id))
    db_session.add(UserPosition(user_id=v.id, position_id=pos.id,
                                start_date=date.today() - timedelta(days=1),
                                is_active=True))
    db_session.commit()
    m = az.user_app_assignments_map(db_session, v.id)
    assert m["ba1"]["roles"] == ["ba_role"]
    assert m["ba1"]["effective"] == ["ba1.x.api.read"]


def test_summary_direct_and_empty(db_session):
    a1, a2, a3, role, p1, p2, u, v = _seed(db_session)
    s = az.users_apps_summary(db_session, [u.id, v.id])
    assert s[u.id] == ["ba1", "ba2"]
    assert s[v.id] == []


def test_summary_counts_current_position_not_expired(db_session):
    a1, a2, a3, role, p1, p2, u, v = _seed(db_session)
    pos = Position(code="ba_pos2", title="p", is_active=True)
    db_session.add(pos); db_session.commit()
    db_session.add(PositionAppRole(position_id=pos.id, app_id=a1.id, role_id=role.id))
    # puesto VENCIDO → no cuenta
    expired = UserPosition(user_id=v.id, position_id=pos.id,
                            start_date=date.today() - timedelta(days=30),
                            end_date=date.today() - timedelta(days=1),
                            is_active=True)
    db_session.add(expired)
    db_session.commit()
    assert az.users_apps_summary(db_session, [v.id])[v.id] == []
    # cerrar el registro vencido (uq_active_user_position_new solo permite UN
    # registro is_active=True por (user_id, position_id) — patrón real de
    # renovación de puesto: desactivar el viejo antes de abrir el vigente).
    expired.is_active = False
    db_session.commit()
    # puesto VIGENTE → cuenta
    db_session.add(UserPosition(user_id=v.id, position_id=pos.id,
                                start_date=date.today() - timedelta(days=1),
                                is_active=True))
    db_session.commit()
    assert az.users_apps_summary(db_session, [v.id])[v.id] == ["ba1"]


def test_summary_ignores_deny_only(db_session):
    a1, a2, a3, role, p1, p2, u, v = _seed(db_session)
    db_session.add(UserAppPerm(user_id=v.id, app_id=a1.id, perm_id=p1.id, allow=False))
    db_session.commit()
    assert az.users_apps_summary(db_session, [v.id])[v.id] == []


def test_summary_empty_input(db_session):
    assert az.users_apps_summary(db_session, []) == {}
