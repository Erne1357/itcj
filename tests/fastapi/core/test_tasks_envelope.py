"""F3 Task 5: tasks.py flipea a {"success": true} + runs pagination top-level."""
from itcj2.core.api import tasks as tasks_api


def test_list_definitions_envelope(db_session):
    resp = tasks_api.list_definitions(user={"sub": "1"}, db=db_session)
    assert resp["success"] is True
    assert "status" not in resp
    assert isinstance(resp["data"], list)


def test_list_runs_pagination_top_level(db_session):
    resp = tasks_api.list_runs(
        status=None, task_name=None, app_name=None, days=7, page=1, per_page=50,
        user={"sub": "1"}, db=db_session,
    )
    assert resp["success"] is True
    assert "meta" not in resp
    for k in ("total", "page", "per_page", "total_pages"):
        assert k in resp
