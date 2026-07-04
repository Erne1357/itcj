"""F1a (C3): endpoints batch — envelope success:true desde el nacimiento."""
import pytest

from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db


@pytest.fixture()
def client_db(app_client, db_session):
    """TestClient con get_db overrideado a la sesión real-PG con savepoints."""
    def override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = override
    yield app_client, db_session
    app_client.app.dependency_overrides.pop(get_db, None)


def _seed_minimal(db):
    app = App(key="bat1", name="bat1", is_active=True)
    db.add(app); db.commit()
    role = Role(name="bat1_role"); db.add(role); db.commit()
    u = User(first_name="B", last_name="Api", is_active=True)
    db.add(u); db.commit()
    db.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id)); db.commit()
    return app, role, u


def test_app_assignments_envelope_and_shape(client_db, auth_headers):
    client, db = client_db
    app, role, u = _seed_minimal(db)
    resp = client.get(f"/api/core/v2/users/{u.id}/app-assignments",
                      headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    entry = body["data"]["bat1"]
    assert entry == {"roles": ["bat1_role"], "perms": [], "effective": []}
    for v in body["data"].values():  # contrato C3 en todas las llaves
        assert set(v.keys()) == {"roles", "perms", "effective"}


def test_app_assignments_user_not_found(client_db, auth_headers):
    client, _ = client_db
    resp = client.get("/api/core/v2/users/99999999/app-assignments",
                      headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Usuario no encontrado"


def test_apps_summary(client_db, auth_headers):
    client, db = client_db
    app, role, u = _seed_minimal(db)
    v = User(first_name="S", last_name="Sin", is_active=True)
    db.add(v); db.commit()
    resp = client.get(f"/api/core/v2/users/apps-summary?ids={u.id},{v.id}",
                      headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][str(u.id)] == ["bat1"]
    assert body["data"][str(v.id)] == []


def test_apps_summary_invalid_ids(client_db, auth_headers):
    client, _ = client_db
    resp = client.get("/api/core/v2/users/apps-summary?ids=1,abc",
                      headers=auth_headers)
    assert resp.status_code == 400
    assert isinstance(resp.json()["error"], str)


def test_apps_summary_empty_and_too_many(client_db, auth_headers):
    client, _ = client_db
    assert client.get("/api/core/v2/users/apps-summary?ids=",
                      headers=auth_headers).status_code == 400
    ids = ",".join(str(i) for i in range(1, 102))
    assert client.get(f"/api/core/v2/users/apps-summary?ids={ids}",
                      headers=auth_headers).status_code == 400


def test_batch_endpoints_require_auth(app_client):
    assert app_client.get("/api/core/v2/users/1/app-assignments").status_code == 401
    assert app_client.get("/api/core/v2/users/apps-summary?ids=1").status_code == 401
