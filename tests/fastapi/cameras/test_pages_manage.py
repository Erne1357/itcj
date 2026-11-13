"""Páginas de gestión y bitácora de Cámaras (mock-based: sin base de datos)."""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

from itcj2.apps.cameras.services import secrets
from itcj2.apps.cameras.services.dvr_service import Viewer
from itcj2.database import get_db
from tests.conftest import make_jwt

M = "itcj2.apps.cameras.pages.manage"
S = f"{M}.dvr_service"


def _hdr(role="admin", uid=200):
    return {"Cookie": f"itcj_token={make_jwt(user_id=uid, role=role)}"}


def _viewer(**kw):
    base = dict(user_id=200, see_all=True, dept_ids=frozenset(), can_manage=True,
                can_update_password=True, can_audit=True)
    return Viewer(**{**base, **kw})


def _dvr(id=1):
    return SimpleNamespace(
        id=id, name="DVR Prueba", location="Edificio A", brand="Hikvision", model="X1",
        channels=8, username="usr-zz9", notes="nota-x", is_active=True,
        password_cipher="SECRETO-PW", pattern_cipher="SECRETO-PAT",
        departments=[SimpleNamespace(id=1, name="Dirección")])


@contextmanager
def _ctx(app_client, viewer=None, **patches):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    stack = [patch(f"{S}.viewer_for", return_value=viewer or _viewer()),
             patch(f"{M}._departments", return_value=[SimpleNamespace(id=1, name="Dirección"),
                                                      SimpleNamespace(id=2, name="Centro de Cómputo")]),
             patch(f"{S}.list_visible", return_value=[])]
    stack += [patch(f"{S}.{k}", **v) for k, v in patches.items()]
    try:
        for p in stack:
            p.start()
        yield
    finally:
        for p in stack:
            p.stop()
        app_client.app.dependency_overrides.pop(get_db, None)


def test_manage_routes_registered(app_client):
    with _ctx(app_client, get_visible=dict(return_value=None), audit_page=dict(return_value=([], 0))):
        for method, path in (("get", "/cameras/dvrs/new"), ("get", "/cameras/dvrs/1/edit"),
                             ("post", "/cameras/dvrs/1"), ("post", "/cameras/dvrs/1/deactivate"),
                             ("get", "/cameras/audit")):
            r = getattr(app_client, method)(path, headers=_hdr(), follow_redirects=False)
            assert r.status_code != 405, f"{method} {path}"
            assert not (r.status_code == 404 and "No encontrado" not in r.text), f"{method} {path}"


def test_head_cannot_manage(app_client):
    v = _viewer(can_manage=False, can_audit=False, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v, get_visible=dict(return_value=_dvr())):
        assert app_client.get("/cameras/dvrs/new", headers=_hdr()).status_code == 403
        assert app_client.post("/cameras/dvrs/1", headers=_hdr(), data={"name": "x"}).status_code == 403
        assert app_client.post("/cameras/dvrs/1/deactivate", headers=_hdr()).status_code == 403


def test_edit_form_is_write_only(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        r = app_client.get("/cameras/dvrs/1/edit", headers=_hdr())
    assert r.status_code == 200
    assert "Patrón configurado" in r.text and "Contraseña configurada" in r.text
    for secret in ("SECRETO-PW", "SECRETO-PAT", "usr-zz9", "nota-x"):
        assert secret not in r.text
    assert "DVR Prueba" in r.text and "Edificio A" in r.text
    for name in ("remove_password", "remove_pattern", "remove_username", "remove_notes"):
        assert f'name="{name}"' in r.text


def test_edit_out_of_scope_404(app_client):
    with _ctx(app_client, get_visible=dict(return_value=None)):
        r = app_client.get("/cameras/dvrs/9/edit", headers=_hdr())
        assert r.status_code == 404
        r = app_client.post("/cameras/dvrs/9", headers=_hdr(), data={"name": "x"})
        assert r.status_code == 404
        r = app_client.post("/cameras/dvrs/9/deactivate", headers=_hdr())
        assert r.status_code == 404 and "No encontrado" in unquote(r.headers["x-cam-error"])


def test_create_validation_422(app_client):
    msg = "Captura al menos la contraseña o el patrón."
    with _ctx(app_client, create=dict(side_effect=ValueError(msg))):
        r = app_client.post("/cameras/dvrs", headers=_hdr(),
                            data={"name": "Mi DVR", "location": "Lab", "password": "sec-123",
                                  "password_confirm": "sec-123"})
    assert r.status_code == 422
    assert unquote(r.headers["x-cam-error"]) == msg
    assert 'value="Mi DVR"' in r.text and 'value="Lab"' in r.text
    assert "sec-123" not in r.text


def test_create_passes_pattern_from_hidden_input(app_client):
    with _ctx(app_client):
        with patch(f"{S}.create", return_value=_dvr()) as cr:
            r = app_client.post("/cameras/dvrs", headers={**_hdr(), "HX-Request": "true"},
                                data={"name": " Mi DVR ", "pattern": "1259", "channels": "16",
                                      "department_ids": ["1", "2"], "password": "  x y ",
                                      "password_confirm": "  x y "})
    assert r.status_code == 200 and r.headers["hx-redirect"] == "/cameras/"
    data = cr.call_args.args[1]
    assert data.pattern == "1259" and data.channels == 16 and data.name == "Mi DVR"
    assert data.department_ids == [1, 2] and data.password == "  x y "
    assert cr.call_args.args[2] == 200


def test_password_confirmation_mismatch_422(app_client):
    with _ctx(app_client):
        with patch(f"{S}.create") as cr:
            r = app_client.post("/cameras/dvrs", headers=_hdr(),
                                data={"name": "a", "password": "a", "password_confirm": "b"})
    assert r.status_code == 422 and r.headers["x-cam-error"]
    cr.assert_not_called()


def test_create_without_key_503(app_client):
    with _ctx(app_client, create=dict(side_effect=secrets.CamerasKeyMissing("x"))):
        r = app_client.post("/cameras/dvrs", headers=_hdr(), data={"name": "a", "pattern": "1259"})
    assert r.status_code == 503
    assert "llave" in unquote(r.headers["x-cam-error"])


def test_update_wrong_key_503_and_remove_flags(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              update=dict(side_effect=secrets.CamerasKeyMissing("x"))):
        r = app_client.post("/cameras/dvrs/1", headers=_hdr(), data={"name": "a"})
    assert r.status_code == 503 and "llave" in unquote(r.headers["x-cam-error"])
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        with patch(f"{S}.update", return_value=_dvr()) as up:
            r = app_client.post("/cameras/dvrs/1", headers=_hdr(),
                                data={"name": "a", "remove_username": "on", "remove_notes": "on"},
                                follow_redirects=False)
    assert r.status_code in (200, 303)
    d = up.call_args.args[2]
    assert d.remove_username and d.remove_notes and not d.remove_password


def test_deactivate(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        with patch(f"{S}.deactivate") as de:
            r = app_client.post("/cameras/dvrs/1/deactivate", headers=_hdr())
    assert r.status_code == 200
    de.assert_called_once()


def test_card_tools_only_for_manage(app_client):
    for can_manage, expect in ((True, True), (False, False)):
        v = _viewer(can_manage=can_manage, see_all=can_manage, dept_ids=frozenset({1}))
        with _ctx(app_client, viewer=v):
            with patch(f"{S}.list_visible", return_value=[_dvr()]):
                r = app_client.get("/cameras/", headers=_hdr())
        assert ("data-cam-deactivate" in r.text) is expect
        assert ("/cameras/dvrs/1/edit" in r.text) is expect
        assert ("/cameras/dvrs/new" in r.text) is expect


def test_audit_requires_perm(app_client):
    rows = [{"id": 1, "dvr_id": 1, "dvr_name": "DVR Prueba", "actor_id": 5, "actor_name": "Ana Pérez",
             "action": "update", "detail": {"fields": ["name"]}, "created_at": datetime(2026, 11, 13, 9, 5)}]
    with _ctx(app_client, viewer=_viewer(can_audit=False), audit_page=dict(return_value=(rows, 1))):
        assert app_client.get("/cameras/audit", headers=_hdr()).status_code == 403
    with _ctx(app_client, audit_page=dict(return_value=(rows, 1))):
        r = app_client.get("/cameras/audit", headers=_hdr())
        assert r.status_code == 200
        assert 'id="cam-audit-rows"' in r.text and "Ana Pérez" in r.text and "DVR Prueba" in r.text
        assert "13/11/2026 09:05" in r.text
        r = app_client.get("/cameras/audit?page=1&action=update", headers={**_hdr(), "HX-Request": "true"})
        assert r.status_code == 200 and "<html" not in r.text and "Ana Pérez" in r.text


def test_edit_not_found_direct_navigation_full_page(app_client):
    with _ctx(app_client, get_visible=dict(return_value=None)):
        r = app_client.get("/cameras/dvrs/999/edit", headers=_hdr())
    assert r.status_code == 404 and "<html" in r.text and "No encontrado" in r.text and "cam-" in r.text


def test_dvr_form_password_managers_and_inactive_department(app_client):
    d = _dvr()
    d.departments = [SimpleNamespace(id=7, name="Depto Viejo", is_active=False)]
    with _ctx(app_client, get_visible=dict(return_value=d)):
        r = app_client.get("/cameras/dvrs/1/edit", headers=_hdr())
    assert r.text.count('autocomplete="new-password"') == 2
    assert "Depto Viejo (inactivo)" in r.text
    import re
    assert re.search(r'value="7" checked', r.text)


def test_audit_actor_filter_select(app_client):
    with _ctx(app_client, audit_page=dict(return_value=([], 0)),
              audit_actors=dict(return_value=[(5, "Ana Pérez López")])):
        r = app_client.get("/cameras/audit?actor_id=5", headers=_hdr())
    assert 'name="actor_id"' in r.text
    assert '<option value="5" selected>Ana Pérez López</option>' in r.text
