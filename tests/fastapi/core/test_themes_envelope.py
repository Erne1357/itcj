"""F3 Task 4: themes.py flipea a {"success": true}."""
from itcj2.core.api import themes as themes_api


def test_list_themes_envelope(db_session):
    resp = themes_api.list_themes(user={"sub": "1"}, db=db_session)
    assert resp["success"] is True
    assert "status" not in resp
    assert isinstance(resp["data"], list)


def test_active_theme_envelope(app_client):
    # /themes/active es público (sin auth)
    r = app_client.get("/api/core/v2/themes/active")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "data" in body


def test_themes_stats_envelope(db_session):
    resp = themes_api.get_themes_stats(user={"sub": "1"}, db=db_session)
    assert resp["success"] is True
    assert set(resp["data"]) == {"total", "active"}
