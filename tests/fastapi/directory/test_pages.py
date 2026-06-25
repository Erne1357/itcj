from unittest.mock import MagicMock, patch

from itcj2.database import get_db
from tests.conftest import make_jwt


def _hdr(role="admin", uid=200, cn=None):
    return {"Cookie": f"itcj_token={make_jwt(user_id=uid, role=role, cn=cn)}"}


def _override_db(app_client):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()


def test_directory_routes_registered(app_client):
    # FastAPI uses _IncludedRouter (no .path attr); check via OpenAPI schema instead.
    resp = app_client.get("/api/openapi.json")
    paths = set(resp.json().get("paths", {}).keys())
    assert "/directory/" in paths
    assert "/directory/list" in paths
    assert "/directory/entries" in paths
    assert "/directory/positions/{position_id}/extension" in paths


def test_index_redirects_anonymous(app_client):
    _override_db(app_client)
    try:
        resp = app_client.get("/directory/", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/itcj/login" in resp.headers.get("location", "")
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


def test_index_student_redirected(app_client):
    _override_db(app_client)
    try:
        resp = app_client.get("/directory/", headers=_hdr(role="student", uid=100, cn="20210001"), follow_redirects=False)
        assert resp.status_code == 302
        assert "/itcj/m/" in resp.headers.get("location", "")
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


@patch("itcj2.apps.directory.pages.directory.directory_service.list_directory", return_value=[])
@patch("itcj2.apps.directory.pages.directory._departments", return_value=[])
def test_index_admin_ok(mock_deps, mock_list, app_client):
    _override_db(app_client)
    try:
        resp = app_client.get("/directory/", headers=_hdr())
        assert resp.status_code == 200
        assert 'id="dir-list"' in resp.text
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


@patch("itcj2.apps.directory.pages.directory.directory_service.list_directory", return_value=[])
@patch("itcj2.apps.directory.pages.directory.directory_service.create_entry")
def test_create_entry_admin(mock_create, mock_list, app_client):
    _override_db(app_client)
    try:
        resp = app_client.post(
            "/directory/entries",
            data={"department_id": "1", "label": "Recepción", "extension": "2000"},
            headers=_hdr(),
        )
        assert resp.status_code == 200
        mock_create.assert_called_once()
        assert "Sin resultados" in resp.text   # _render_list con groups=[]
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


@patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True)
@patch("itcj2.core.services.authz_cache.cached_perms", return_value=set())
def test_create_entry_forbidden_without_perm(mock_perms, mock_assign, app_client):
    _override_db(app_client)
    try:
        resp = app_client.post(
            "/directory/entries",
            data={"department_id": "1", "label": "X", "extension": "2000"},
            headers=_hdr(role="staff", uid=300),
        )
        assert resp.status_code == 403
        # Page routes return HTML error page (403), not JSON — verify status only.
        assert "403" in resp.text
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


@patch("itcj2.apps.directory.pages.directory.directory_service.list_directory", return_value=[])
def test_list_partial_empty_dept_ok(mock_list, app_client):
    _override_db(app_client)
    try:
        resp = app_client.get("/directory/list?q=ana&filter_dept=&source=all", headers=_hdr())
        assert resp.status_code == 200
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


@patch("itcj2.apps.directory.pages.directory.directory_service.list_directory", return_value=[])
def test_list_partial_valid_dept_coerced(mock_list, app_client):
    _override_db(app_client)
    try:
        resp = app_client.get("/directory/list?q=&filter_dept=3&source=position", headers=_hdr())
        assert resp.status_code == 200
        _, kwargs = mock_list.call_args
        assert kwargs.get("department_id") == 3
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)
