"""Páginas de consulta de Cámaras (mock-based: sin base de datos)."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from itcj2.apps.cameras.services import dvr_service, secrets
from itcj2.apps.cameras.services.dvr_service import Viewer
from itcj2.database import get_db
from tests.conftest import make_jwt

V = "itcj2.apps.cameras.pages.viewer.dvr_service"


def _hdr(role="admin", uid=200, cn=None):
    return {"Cookie": f"itcj_token={make_jwt(user_id=uid, role=role, cn=cn)}"}


def _viewer(**kw):
    base = dict(user_id=200, see_all=True, dept_ids=frozenset(), can_manage=True,
                can_update_password=True, can_audit=True)
    return Viewer(**{**base, **kw})


def _dvr(id=1, name="DVR Prueba"):
    return SimpleNamespace(
        id=id, name=name, location="Edificio A", brand="Hikvision", model="X1", channels=8,
        username="usr-zz9", notes="nota-x", password_cipher="c1", pattern_cipher="c2",
        departments=[SimpleNamespace(id=1, name="Dirección")])


@contextmanager
def _ctx(app_client, viewer=None, **patches):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    stack = [patch(f"{V}.viewer_for", return_value=viewer or _viewer())]
    stack += [patch(f"{V}.{k}", **v) for k, v in patches.items()]
    try:
        for p in stack:
            p.start()
        yield
    finally:
        for p in stack:
            p.stop()
        app_client.app.dependency_overrides.pop(get_db, None)


def _revealed(pattern="1259", password="  x y "):
    return dvr_service.Revealed(password, pattern, "usr-zz9", "nota-x", None, None)


def test_routes_registered(app_client):
    with _ctx(app_client, list_visible=dict(return_value=[]), get_visible=dict(return_value=None)):
        for method, path in (("get", "/cameras/"), ("get", "/cameras/list"),
                             ("post", "/cameras/dvrs/1/reveal"),
                             ("get", "/cameras/dvrs/1/password"),
                             ("post", "/cameras/dvrs/1/password")):
            r = getattr(app_client, method)(path, follow_redirects=False)
            assert r.status_code not in (405,), f"{method} {path}"
            assert not (r.status_code == 404 and "No encontrado" not in r.text), f"{method} {path}"


def test_index_redirects_anonymous(app_client):
    with _ctx(app_client):
        r = app_client.get("/cameras/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/itcj/login" in r.headers["location"]


def test_index_student_redirected(app_client):
    with _ctx(app_client):
        r = app_client.get("/cameras/", headers=_hdr("student", 100, "20210001"), follow_redirects=False)
    assert r.status_code == 302 and "/itcj/m/" in r.headers["location"]


def test_index_no_secret_leak(app_client):
    with _ctx(app_client, list_visible=dict(return_value=[_dvr()])):
        r = app_client.get("/cameras/", headers=_hdr())
    assert r.status_code == 200
    assert "DVR Prueba" in r.text
    assert "usr-zz9" not in r.text and "nota-x" not in r.text


def test_base_disables_htmx_history(app_client):
    with _ctx(app_client, list_visible=dict(return_value=[])):
        r = app_client.get("/cameras/", headers=_hdr())
    assert 'hx-history="false"' in r.text


def test_reveal_no_store(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              reveal=dict(return_value=_revealed())):
        r = app_client.post("/cameras/dvrs/1/reveal", headers=_hdr())
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    assert 'data-pattern="1259"' in r.text
    assert "<p class=\"cam-pw\" data-cam-pw>  x y </p>" in r.text
    assert "<template data-cam-sealed>" in r.text and 'data-seal-after="30"' in r.text


def test_reveal_out_of_scope_404(app_client):
    with _ctx(app_client, get_visible=dict(return_value=None), reveal=dict()) as _:
        r = app_client.post("/cameras/dvrs/9/reveal", headers=_hdr())
    assert r.status_code == 404


def test_reveal_deactivated_404(app_client):
    # get_visible filtra is_active: un DVR de baja llega aquí como None.
    test_reveal_out_of_scope_404(app_client)


def test_reveal_without_key_503(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              reveal=dict(side_effect=secrets.CamerasKeyMissing("x"))):
        r = app_client.post("/cameras/dvrs/1/reveal", headers=_hdr())
    assert r.status_code == 503
    assert "llave" in r.headers["x-cam-error"].lower() or "%" in r.headers["x-cam-error"]


def test_reveal_wrong_key_503(app_client):
    from urllib.parse import unquote
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              reveal=dict(side_effect=secrets.CamerasDecryptError("x"))):
        r = app_client.post("/cameras/dvrs/1/reveal", headers=_hdr())
    assert r.status_code == 503
    assert "no coincide" in unquote(r.headers["x-cam-error"])


def test_head_password_form_keeps_spaces(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        with patch(f"{V}.set_password", return_value=True) as sp:
            r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                                data={"password": "  x y ", "password_confirm": "  x y "})
    assert r.status_code == 200
    assert sp.call_args.args[3] == "  x y "


def test_password_mismatch_422(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        with patch(f"{V}.set_password") as sp:
            r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                                data={"password": "a", "password_confirm": "b"})
    assert r.status_code == 422 and r.headers["x-cam-error"]
    sp.assert_not_called()


def test_password_empty_422(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              set_password=dict(side_effect=ValueError("La contraseña no puede estar vacía."))):
        r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                            data={"password": "", "password_confirm": ""})
    assert r.status_code == 422 and r.headers["x-cam-error"]


def test_password_without_permission_404(app_client):
    v = _viewer(can_manage=False, can_update_password=False, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v, get_visible=dict(return_value=_dvr())):
        with patch(f"{V}.set_password") as sp:
            r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                                data={"password": "a", "password_confirm": "a"})
    assert r.status_code == 404
    sp.assert_not_called()


def test_password_service_refuses_404(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              set_password=dict(return_value=False)):
        r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                            data={"password": "a", "password_confirm": "a"})
    assert r.status_code == 404 and "cam-card" not in r.text


def test_empty_state_unlinked_position(app_client):
    v = _viewer(see_all=False, dept_ids=frozenset(), can_manage=False, can_update_password=False)
    with _ctx(app_client, viewer=v, list_visible=dict(return_value=[])):
        r = app_client.get("/cameras/", headers=_hdr())
    assert "Tu puesto no está ligado" in r.text


def test_empty_state_department_without_dvr(app_client):
    v = _viewer(see_all=False, dept_ids=frozenset({1}), can_manage=False)
    with _ctx(app_client, viewer=v, list_visible=dict(return_value=[])):
        r = app_client.get("/cameras/list", headers=_hdr())
    assert "Tu departamento no tiene DVR" in r.text


def test_reveal_password_exact_inner_text(app_client):
    import re
    with _ctx(app_client, get_visible=dict(return_value=_dvr()),
              reveal=dict(return_value=_revealed(password="  x y <&"))):
        r = app_client.post("/cameras/dvrs/1/reveal", headers=_hdr())
    m = re.search(r"<p class=\"cam-pw\" data-cam-pw>(.*?)</p>", r.text, re.S)
    assert m.group(1) == "  x y &lt;&amp;"


def test_password_errors_keep_card_intact(app_client):
    """422/503 se pintan en el hueco; el éxito sigue apuntando a la tarjeta."""
    for kw, code in ((dict(return_value=True), None),
                     (dict(side_effect=ValueError("vacía")), 422),
                     (dict(side_effect=secrets.CamerasKeyMissing("x")), 503)):
        with _ctx(app_client, get_visible=dict(return_value=_dvr()), set_password=kw):
            r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                                data={"password": "a", "password_confirm": "a"})
        if code is None:
            assert r.status_code == 200 and "hx-retarget" not in r.headers
            assert 'id="cam-dvr-1"' in r.text
        else:
            assert r.status_code == code
            assert r.headers["hx-retarget"] == "#cam-pwslot-1"
            assert r.headers["hx-reswap"] == "innerHTML"
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        r = app_client.post("/cameras/dvrs/1/password", headers=_hdr(),
                            data={"password": "a", "password_confirm": "b"})
    assert r.status_code == 422 and r.headers["hx-retarget"] == "#cam-pwslot-1"


def test_not_found_carries_header_same_message(app_client):
    from urllib.parse import unquote
    with _ctx(app_client, get_visible=dict(return_value=None)):
        hx = {**_hdr(), "HX-Request": "true"}
        r1 = app_client.post("/cameras/dvrs/9/password", headers=hx,
                             data={"password": "a", "password_confirm": "a"})
        r2 = app_client.post("/cameras/dvrs/9/reveal", headers=hx)
    assert r1.status_code == r2.status_code == 404
    assert unquote(r1.headers["x-cam-error"]) == unquote(r2.headers["x-cam-error"]) == "No encontrado."
    assert r1.headers["hx-retarget"] == "#cam-pwslot-9" and "hx-retarget" not in r2.headers


def test_index_q_prefilters_and_fills_input(app_client):
    with _ctx(app_client, list_visible=dict(return_value=[])) as _:
        with patch(f"{V}.list_visible", return_value=[]) as lv:
            r = app_client.get("/cameras/?q=abc", headers=_hdr())
    assert lv.call_args.args[2] == "abc"
    assert 'value="abc"' in r.text and 'hx-get="/cameras/list"' in r.text


def test_non_admin_without_assignment_forbidden(app_client):
    with _ctx(app_client, list_visible=dict(return_value=[])):
        with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=False):
            r = app_client.get("/cameras/", headers=_hdr("staff", 300), follow_redirects=False)
    assert r.status_code in (302, 307, 403)
    assert "DVR Prueba" not in r.text


def test_not_found_direct_navigation_full_page(app_client):
    with _ctx(app_client, get_visible=dict(return_value=None)):
        r = app_client.post("/cameras/dvrs/9/reveal", headers=_hdr())
        h = app_client.post("/cameras/dvrs/9/reveal", headers={**_hdr(), "HX-Request": "true"})
    assert r.status_code == 404 and "<html" in r.text and "No encontrado" in r.text and "cam-" in r.text
    assert h.status_code == 404 and "<html" not in h.text


def test_password_form_manager_hints_and_cancel(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr())):
        r = app_client.get("/cameras/dvrs/1/password", headers=_hdr())
    assert r.text.count('autocomplete="new-password"') == 2
    assert 'data-cam-pw-cancel="1"' in r.text
