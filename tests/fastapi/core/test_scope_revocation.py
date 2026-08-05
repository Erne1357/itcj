"""El scope por subárbol debe ser revocable y fail-closed.

`subtree_scope_for` se llama directamente desde las apps (helpdesk/maint), no a
través de `resolve_read_scope`, así que tiene que aplicar por su cuenta las mismas
reglas que el resolver de permisos: un deny explícito lo apaga, un puesto inactivo
no ancla, y un departamento dado de baja no concede nada.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.core.services.scope_service import granting_departments, subtree_scope_for
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

PERM = "helpdesk.tickets.api.read.subtree"


def _setup(db, *, position_active=True, department_active=True):
    """Usuario anclado en un depto (con un hijo) por un puesto que otorga PERM."""
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=PERM).first()
    if not perm:
        perm = Permission(app_id=app.id, code=PERM, name=PERM)
        db.add(perm); db.commit(); db.refresh(perm)

    anchor = Department(code="rev_anchor", name="anchor", is_active=department_active)
    db.add(anchor); db.commit(); db.refresh(anchor)
    child = Department(code="rev_child", name="child", parent_id=anchor.id, is_active=True)
    db.add(child); db.commit(); db.refresh(child)

    u = User(first_name="R", last_name="Revoke", is_active=True)
    db.add(u); db.commit(); db.refresh(u)

    pos = Position(code="rev_pos", title="Jefe", department_id=anchor.id,
                   is_active=position_active, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=u.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return app, perm, u, anchor, child


def test_baseline_grants_subtree(db_session):
    """Control: sin nada que lo revoque, el scope es el subárbol completo."""
    _app, _perm, u, anchor, child = _setup(db_session)
    assert subtree_scope_for(db_session, u.id, "helpdesk", PERM) == {anchor.id, child.id}


def test_explicit_deny_revokes_subtree_scope(db_session):
    """Un deny a nivel usuario apaga el permiso — y con él, el scope."""
    app, perm, u, _anchor, _child = _setup(db_session)
    db_session.add(UserAppPerm(user_id=u.id, app_id=app.id, perm_id=perm.id, allow=False))
    db_session.commit()

    assert subtree_scope_for(db_session, u.id, "helpdesk", PERM) == set()


def test_inactive_position_does_not_anchor_scope(db_session):
    """Un puesto dado de baja no puede seguir siendo ancla del subárbol."""
    _app, _perm, u, _anchor, _child = _setup(db_session, position_active=False)

    assert granting_departments(db_session, u.id, "helpdesk", PERM) == set()
    assert subtree_scope_for(db_session, u.id, "helpdesk", PERM) == set()


def test_inactive_anchor_department_grants_nothing(db_session):
    """Departamento ancla dado de baja → fail-closed, no `{anchor}`.

    El mapa de descendientes solo contiene departamentos activos; el default del
    lookup no puede reintroducir el ancla por la puerta de atrás.
    """
    _app, _perm, u, _anchor, _child = _setup(db_session, department_active=False)

    assert subtree_scope_for(db_session, u.id, "helpdesk", PERM) == set()
