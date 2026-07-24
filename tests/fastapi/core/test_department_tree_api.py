"""GET /departments/tree (C3): envelope nuevo + orden de rutas."""
from itcj2.core.api import departments as departments_api


def test_tree_endpoint_envelope(db_session):
    resp = departments_api.get_departments_tree(user={"sub": "1"}, db=db_session)
    assert resp["success"] is True
    assert isinstance(resp["data"], list)


def test_tree_route_resolves_before_dept_id(app_client, auth_headers):
    # Si /tree se registrara DESPUÉS de /{dept_id}, FastAPI intentaría castear
    # "tree" a int → 422. Lectura sola contra la BD dev (sin mutación).
    r = app_client.get("/api/core/v2/departments/tree", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_tree_requires_auth(app_client):
    r = app_client.get("/api/core/v2/departments/tree")
    assert r.status_code == 401
