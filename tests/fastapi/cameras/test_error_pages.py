"""Página de error propia de Cámaras (handler global en itcj2/main.py)."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from itcj2.apps.cameras.services.dvr_service import Viewer
from itcj2.database import get_db
from tests.conftest import make_jwt

AUTHZ = "itcj2.core.services.authz_service"


def _hdr(role=None, uid=777):
    return {"Cookie": f"itcj_token={make_jwt(user_id=uid, role=role)}"}


@contextmanager
def _db(app_client):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


def test_404_uses_cameras_template(app_client):
    r = app_client.get("/cameras/ruta-inexistente", follow_redirects=False)
    assert r.status_code == 404
    assert "cam-error" in r.text and "Ir al inicio" in r.text and 'href="/cameras/"' in r.text
    assert "CLOSE_APP" not in r.text


def test_403_without_app_access_exits_to_dashboard(app_client):
    with _db(app_client), patch(f"{AUTHZ}.has_any_assignment", return_value=False):
        r = app_client.get("/cameras/", headers=_hdr(), follow_redirects=False)
    assert r.status_code == 403
    assert "cam-error" in r.text and "Ir al panel principal" in r.text
    assert "/itcj/dashboard" in r.text and "mobileBackToDashboard" in r.text
    assert "/static/cameras/js/error.js" in r.text


def test_403_with_app_access_points_to_cameras_home(app_client):
    viewer = Viewer(user_id=777, see_all=False, dept_ids=frozenset({1}), can_manage=False,
                    can_update_password=True, can_audit=False)
    with _db(app_client), patch(f"{AUTHZ}.has_any_assignment", return_value=True), \
            patch("itcj2.apps.cameras.pages.manage.dvr_service.viewer_for", return_value=viewer):
        r = app_client.get("/cameras/audit", headers=_hdr(), follow_redirects=False)
    assert r.status_code == 403
    assert "cam-error" in r.text and "Ir al inicio" in r.text and 'href="/cameras/"' in r.text
    assert "Ir al panel principal" not in r.text
    assert "pídelo a Soporte" in r.text


def test_other_apps_and_api_unchanged(app_client):
    assert "cam-error" not in app_client.get("/help-desk/ruta-inexistente").text
    r = app_client.get("/api/cameras/ruta-inexistente")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
