"""F5: flip de envelope a {"success": True} en departments/positions/authz.

Los GET read-only van por HTTP (app_client + admin bypass del claim JWT);
las mutaciones se prueban llamando la función del endpoint con db_session
(savepoint rollback — patrón test_subtree_guardrail.py).
"""
import pytest


GET_ENDPOINTS = [
    "/api/core/v2/departments",
    "/api/core/v2/departments/parent-options",
    "/api/core/v2/departments/subdirections",
    "/api/core/v2/positions",
    "/api/core/v2/authz/apps",
    "/api/core/v2/authz/roles",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_get_endpoints_use_success_envelope(app_client, auth_headers, path):
    resp = app_client.get(path, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert "status" not in body
    assert "data" in body


def test_create_department_success_envelope(db_session):
    from itcj2.core.api.departments import create_department, DepartmentCreateBody

    resp = create_department(
        body=DepartmentCreateBody(code="f5_env_dep", name="F5 Envelope"),
        user={"sub": "1"},
        db=db_session,
    )
    assert resp["success"] is True
    assert "status" not in resp


def test_update_department_success_envelope(db_session):
    from itcj2.core.api.departments import (
        create_department, update_department,
        DepartmentCreateBody, DepartmentUpdateBody,
    )

    created = create_department(
        body=DepartmentCreateBody(code="f5_env_dep2", name="F5 Env 2"),
        user={"sub": "1"},
        db=db_session,
    )
    resp = update_department(
        dept_id=created["data"]["id"],
        body=DepartmentUpdateBody(name="F5 Env 2 bis"),
        user={"sub": "1"},
        db=db_session,
    )
    assert resp["success"] is True
    assert "status" not in resp


def test_user_perm_grant_keeps_warning_key(db_session):
    """El flip NO pierde la clave warning del guardrail (authz.add_user_perm)."""
    from itcj2.core.api.authz import add_user_perm, UserPermBody
    from itcj2.core.models.app import App
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.user import User

    app = App(key="f5env", name="f5env", is_active=True)
    db_session.add(app); db_session.commit(); db_session.refresh(app)
    perm = Permission(app_id=app.id, code="f5env.tickets.api.read.subtree", name="s")
    db_session.add(perm); db_session.commit()
    u = User(first_name="F5", last_name="Env", is_active=True)
    db_session.add(u); db_session.commit(); db_session.refresh(u)

    resp = add_user_perm(
        app_key=app.key, user_id=u.id,
        body=UserPermBody(code=perm.code, allow=True),
        user={"sub": "1"}, db=db_session,
    )
    assert resp["success"] is True
    assert "status" not in resp
    assert resp.get("warning") == "scope_departamental_sin_puesto"


def test_position_perm_grant_keeps_warning_key(db_session):
    """Espejo de posiciones: el flip NO pierde la clave warning del guardrail
    (positions.assign_perm_to_position) — puesto SIN departamento + .subtree."""
    from itcj2.core.api.positions import assign_perm_to_position, AssignPermBody
    from itcj2.core.models.app import App
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.position import Position

    app = App(key="f5envpos", name="f5envpos", is_active=True)
    db_session.add(app); db_session.commit(); db_session.refresh(app)
    perm = Permission(app_id=app.id, code="f5envpos.tickets.api.read.subtree", name="s")
    db_session.add(perm); db_session.commit()
    pos = Position(code="f5envpos_pos", title="p", department_id=None, is_active=True)
    db_session.add(pos); db_session.commit(); db_session.refresh(pos)

    resp = assign_perm_to_position(
        position_id=pos.id, app_key=app.key,
        body=AssignPermBody(code=perm.code, allow=True),
        user={"sub": "1"}, db=db_session,
    )
    assert resp["success"] is True
    assert "status" not in resp
    assert resp.get("warning") == "scope_departamental_sin_departamento"
