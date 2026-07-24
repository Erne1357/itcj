"""Guardrail: perm .subtree a puesto SIN department_id → warning (espejo authz.py:514-520).

Un .subtree anclado a un puesto sin departamento no tiene ancla → fail-closed
(scope_service), permiso muerto silencioso. El endpoint debe avisar.
"""
from itcj2.core.api import positions as positions_api
from itcj2.core.api.positions import AssignPermBody
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position


def _fixt(db, key, with_dept=False):
    app = App(key=key, name=key, is_active=True)
    db.add(app)
    db.commit()
    db.refresh(app)
    perm = Permission(app_id=app.id, code=f"{key}.tickets.api.read.subtree", name="s")
    db.add(perm)
    db.commit()
    db.refresh(perm)
    dept_id = None
    if with_dept:
        d = Department(code=f"{key}_d", name="d", is_active=True)
        db.add(d)
        db.commit()
        db.refresh(d)
        dept_id = d.id
    pos = Position(code=f"{key}_pos", title="p", department_id=dept_id, is_active=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return app, perm, pos


def test_subtree_perm_without_department_warns(db_session):
    app, perm, pos = _fixt(db_session, "pgrd1", with_dept=False)
    resp = positions_api.assign_perm_to_position(
        position_id=pos.id, app_key=app.key,
        body=AssignPermBody(code=perm.code, allow=True),
        user={"sub": "1"}, db=db_session)
    assert resp["warning"] == "scope_departamental_sin_departamento"
    assert resp["data"]["updated"] is True  # el grant SÍ se aplica; solo avisa


def test_subtree_perm_with_department_no_warning(db_session):
    app, perm, pos = _fixt(db_session, "pgrd2", with_dept=True)
    resp = positions_api.assign_perm_to_position(
        position_id=pos.id, app_key=app.key,
        body=AssignPermBody(code=perm.code, allow=True),
        user={"sub": "1"}, db=db_session)
    assert "warning" not in resp


def test_non_subtree_perm_no_warning(db_session):
    app, _, pos = _fixt(db_session, "pgrd3", with_dept=False)
    p2 = Permission(app_id=app.id, code="pgrd3.tickets.api.read.all", name="all")
    db_session.add(p2)
    db_session.commit()
    resp = positions_api.assign_perm_to_position(
        position_id=pos.id, app_key=app.key,
        body=AssignPermBody(code="pgrd3.tickets.api.read.all", allow=True),
        user={"sub": "1"}, db=db_session)
    assert "warning" not in resp
