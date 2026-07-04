"""F3 Task 1: GET /authz/roles con id + users_count agregado (sin N+1)."""
from pathlib import Path

import itcj2
from itcj2.core.api import authz as authz_api
from itcj2.core.models.role import Role
from itcj2.core.models.user import User


def _mk_role(db, name):
    r = Role(name=name)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_list_roles_includes_id_and_users_count(db_session):
    r = _mk_role(db_session, "rc_role1")
    for i in range(3):
        db_session.add(User(first_name=f"U{i}", last_name="RC", is_active=True, role_id=r.id))
    db_session.commit()
    resp = authz_api.list_roles(user={"sub": "1"}, db=db_session)
    row = next(x for x in resp["data"] if x["name"] == "rc_role1")
    assert row["id"] == r.id
    assert row["users_count"] == 3


def test_list_roles_zero_when_no_users(db_session):
    _mk_role(db_session, "rc_role_empty")
    resp = authz_api.list_roles(user={"sub": "1"}, db=db_session)
    row = next(x for x in resp["data"] if x["name"] == "rc_role_empty")
    assert row["users_count"] == 0


def test_roles_page_template_uses_role_counts_not_relationship():
    """La plantilla no debe emitir `role.users|length`: el conteo llega por role_counts."""
    tmpl = (Path(itcj2.__file__).parent / "core" / "templates" / "core" /
            "config" / "system" / "roles.html").read_text(encoding="utf-8")
    assert "role.users|length" not in tmpl
    assert "role_counts" in tmpl
