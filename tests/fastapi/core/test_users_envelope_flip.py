"""F4 Task 4: flip de envelope a {"success": True} en users_admin/users.

Shape destino (Global Constraints):
  - listas: {"success": true, "data": [...], "total", "page", "per_page", "total_pages"}
  - item/mutación: {"success": true, "data": {...}}
  - PROHIBIDO: clave "status" y sub-objeto data.pagination / data.users.
"""
import time
from datetime import date

import pytest

from itcj2.core.api import users_admin
from itcj2.core.api.users_admin import CreateUserBody, UpdateUserBody


def _mk_user(db, first, last, username=None, control=None):
    from itcj2.core.models.user import User
    u = User(first_name=first, last_name=last, username=username,
             control_number=control, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _assert_list_envelope(resp):
    assert resp["success"] is True
    assert isinstance(resp["data"], list)
    for key in ("total", "page", "per_page", "total_pages"):
        assert key in resp, f"falta {key} top-level"
    assert "status" not in resp
    assert "pagination" not in resp


def test_list_users_envelope(db_session):
    _mk_user(db_session, "ZZF4ENV", "LISTA", username="zzf4env_lista")
    resp = users_admin.list_users(
        q="ZZF4ENV", role=None, status=None, app=None,
        only_staff=False, page=1, per_page=20,
        user={"sub": "1"}, db=db_session,
    )
    _assert_list_envelope(resp)
    assert any(u["username"] == "zzf4env_lista" for u in resp["data"])


def test_create_user_envelope(db_session):
    ctrl = f"{int(time.time()) % 100000000:08d}"
    resp = users_admin.create_user(
        body=CreateUserBody(full_name="ZZF4ENV CREADO X", user_type="student",
                            control_number=ctrl, password="e2e-Passw0rd!"),
        user={"sub": "1"}, db=db_session,
    )
    assert resp["success"] is True
    assert resp["data"]["control_number"] == ctrl
    assert "status" not in resp


def test_mutations_envelope(db_session):
    u = _mk_user(db_session, "ZZF4ENV", "MUT", username="zzf4env_mut")

    resp = users_admin.reset_user_password(
        user_id=u.id, current_user={"sub": "1"}, db=db_session)
    assert resp["success"] is True and "status" not in resp

    resp = users_admin.toggle_user_status(
        user_id=u.id, current_user={"sub": "1"}, db=db_session)
    assert resp["success"] is True and "status" not in resp
    assert resp["data"]["is_active"] is False

    resp = users_admin.update_user(
        user_id=u.id, body=UpdateUserBody(email="zzf4env@test.mx"),
        current_user={"sub": "1"}, db=db_session)
    assert resp["success"] is True and "status" not in resp


def test_by_app_envelope(db_session):
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user_app_role import UserAppRole

    app = App(key="zzf4envapp", name="ZZF4ENVAPP", is_active=True)
    role = Role(name="zzf4envrole")
    db_session.add_all([app, role])
    db_session.commit()
    u = _mk_user(db_session, "ZZF4ENV", "BYAPP", username="zzf4env_byapp")
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = users_admin.list_users_by_app(
        app_key="zzf4envapp", q=None, page=1, per_page=20,
        user={"sub": "1", "role": "admin"}, db=db_session,
    )
    _assert_list_envelope(resp)
    assert u.id in [x["id"] for x in resp["data"]]
