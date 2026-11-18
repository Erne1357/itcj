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
        channels=8, camera_type=None, cameras_bala=None, cameras_ptz=None, username="usr-zz9", notes="nota-x", is_active=True,
        password_cipher="SECRETO-PW", pattern_cipher="SECRETO-PAT",
        departments=[SimpleNamespace(id=1, name="Dirección")])


@contextmanager
def _ctx(app_client, viewer=None, **patches):
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    stack = [patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True),
             patch("itcj2.core.services.authz_cache.cached_perms",
                   return_value={"cameras.dvrs.page.list", "cameras.audit.page.list"})]
    stack += [patch(f"{S}.viewer_for", return_value=viewer or _viewer()),
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
    assert r.status_code == 200 and r.headers["hx-redirect"] == "/cameras/?ok=registrado&dvr=1"
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


def test_form_error_htmx_retargets_and_keeps_form(app_client):
    with _ctx(app_client, create=dict(side_effect=ValueError("El patrón necesita de 4 a 9 puntos del 1 al 9, sin repetir."))):
        r = app_client.post("/cameras/dvrs", headers={**_hdr(), "HX-Request": "true"},
                            data={"name": "Mi DVR", "pattern": "12", "password": "sec-123",
                                  "password_confirm": "sec-123"})
    assert r.status_code == 422
    assert r.headers["hx-retarget"] == "#cam-form-error" and r.headers["hx-reswap"] == "innerHTML"
    assert "El patrón necesita de 4 a 9 puntos" in r.text
    assert "<form" not in r.text and "sec-123" not in r.text and "Mi DVR" not in r.text


def test_form_error_without_htmx_is_full_page_with_slot(app_client):
    with _ctx(app_client, create=dict(side_effect=ValueError("Error x."))):
        r = app_client.post("/cameras/dvrs", headers=_hdr(), data={"name": "Mi DVR", "pattern": "1259"})
    assert r.status_code == 422 and "hx-retarget" not in r.headers
    assert 'id="cam-form-error"' in r.text and 'tabindex="-1"' in r.text and "Error x." in r.text
    assert "<html" in r.text and "1259" not in r.text


def test_confirmation_copy(app_client):
    with _ctx(app_client):
        r = app_client.post("/cameras/dvrs", headers=_hdr(),
                            data={"name": "a", "password": "a", "password_confirm": "b"})
    assert "La confirmación no coincide con la contraseña." in unquote(r.headers["x-cam-error"])


def test_update_and_deactivate_redirect_with_ok(app_client):
    with _ctx(app_client, get_visible=dict(return_value=_dvr(5))):
        with patch(f"{S}.update", return_value=_dvr(5)):
            r = app_client.post("/cameras/dvrs/5", headers=_hdr(), data={"name": "a"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/cameras/?ok=actualizado&dvr=5"
        with patch(f"{S}.deactivate"):
            r = app_client.post("/cameras/dvrs/5/deactivate", headers=_hdr(), follow_redirects=False)
        assert r.headers["location"] == "/cameras/?ok=baja"


def test_audit_copy_labels(app_client):
    base = {"id": 1, "dvr_id": 1, "dvr_name": "D", "actor_id": 5, "actor_name": "Ana",
            "created_at": datetime(2026, 11, 13, 9, 5)}
    rows = [{**base, "action": "departments_update", "detail": {"departments": []}},
            {**base, "action": "departments_update", "detail": {"departments": [1]}},
            {**base, "action": "departments_update", "detail": {"departments": [1, 2]}},
            {**base, "action": "reveal", "detail": None},
            {**base, "action": "extend", "detail": None}]
    with _ctx(app_client, audit_page=dict(return_value=(rows, 5)),
              audit_actors=dict(return_value=[])):
        r = app_client.get("/cameras/audit", headers=_hdr())
    for txt in ("Sin departamento", "1 departamento<", "2 departamentos", "Vio credenciales",
                "Extendió el tiempo"):
        assert txt in r.text
    assert "departamento(s)" not in r.text and "Reveló" not in r.text
    assert '<option value="extend">Extendió el tiempo</option>' in r.text


# === v4: dados de baja, bitácora precisa, filtros de fecha ===

def test_inactive_page_lists_and_empty_state(app_client):
    item = {"dvr": _dvr(3), "when": datetime(2026, 11, 10, 8, 30), "by": "Ana Pérez"}
    with _ctx(app_client, list_inactive=dict(return_value=[item])):
        r = app_client.get("/cameras/inactive", headers=_hdr())
    assert r.status_code == 200 and "Dados de baja" in r.text and "DVR Prueba" in r.text
    assert 'action="/cameras/dvrs/3/reactivate"' in r.text and "Reactivar DVR" in r.text
    assert "10/11/2026 08:30" in r.text and "Ana Pérez" in r.text
    assert "SECRETO" not in r.text and "usr-zz9" not in r.text
    with _ctx(app_client, list_inactive=dict(return_value=[])):
        r = app_client.get("/cameras/inactive", headers=_hdr())
    assert "No hay DVR dados de baja." in r.text and "Reactivar DVR" not in r.text


def test_inactive_and_reactivate_forbidden_for_head(app_client):
    v = _viewer(can_manage=False, can_audit=False, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v, get_inactive=dict(return_value=_dvr())):
        assert app_client.get("/cameras/inactive", headers=_hdr()).status_code == 403
        assert app_client.post("/cameras/dvrs/1/reactivate", headers=_hdr()).status_code == 403


def test_reactivate_redirects_like_deactivate(app_client):
    with _ctx(app_client, get_inactive=dict(return_value=_dvr(5))):
        with patch(f"{S}.reactivate") as re_:
            r = app_client.post("/cameras/dvrs/5/reactivate", headers=_hdr(), follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/cameras/?ok=reactivado&dvr=5"
            r = app_client.post("/cameras/dvrs/5/reactivate", headers={**_hdr(), "HX-Request": "true"})
            assert r.status_code == 200 and r.headers["hx-redirect"] == "/cameras/?ok=reactivado&dvr=5"
        assert re_.call_count == 2


def test_reactivate_active_or_missing_404(app_client):
    with _ctx(app_client, get_inactive=dict(return_value=None)):
        with patch(f"{S}.reactivate") as re_:
            r = app_client.post("/cameras/dvrs/9/reactivate", headers=_hdr())
    assert r.status_code == 404 and unquote(r.headers["x-cam-error"]) == "No encontrado."
    re_.assert_not_called()


def test_reactivate_service_logs_and_restores(db_session, cam_world, cameras_key):
    from itcj2.apps.cameras.models import CamerasAuditLog
    from itcj2.apps.cameras.schemas.dvr import DvrInput
    from itcj2.apps.cameras.services import dvr_service as svc
    d = svc.create(db_session, DvrInput(name="D", password="pw1"), cam_world.tech)
    assert svc.get_inactive(db_session, d.id) is None  # activo: no aplica
    svc.deactivate(db_session, d, cam_world.tech)
    assert svc.get_inactive(db_session, d.id) is d and svc.get_inactive(db_session, 99999999) is None
    info = [i for i in svc.list_inactive(db_session) if i["dvr"] is d][0]
    assert info["when"] is not None and info["by"]
    svc.reactivate(db_session, d, cam_world.tech)
    assert d.is_active and svc.get_inactive(db_session, d.id) is None
    last = db_session.query(CamerasAuditLog).filter_by(dvr_id=d.id).order_by(CamerasAuditLog.id.desc()).first()
    assert last.action == "reactivate" and last.detail is None


def test_deactivate_dialog_copy_and_inactive_link(app_client):
    with _ctx(app_client):
        r = app_client.get("/cameras/", headers=_hdr())
    assert "Podrás reactivarlo desde Dados de baja." in r.text
    assert 'href="/cameras/inactive"' in r.text and "cam-btn__label" in r.text
    v = _viewer(can_manage=False, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v):
        r = app_client.get("/cameras/", headers=_hdr())
    assert "/cameras/inactive" not in r.text


def test_flash_after_baja_links_to_inactive_and_reactivated_highlights(app_client):
    with _ctx(app_client):
        with patch("itcj2.apps.cameras.pages.viewer.dvr_service.list_visible", return_value=[_dvr()]):
            r = app_client.get("/cameras/?ok=baja", headers=_hdr())
            assert "DVR dado de baja. Puedes reactivarlo en" in r.text
            assert '<a href="/cameras/inactive">Dados de baja</a>' in r.text
            r = app_client.get("/cameras/?ok=reactivado&dvr=1", headers=_hdr())
    assert "DVR reactivado." in r.text and r.text.count("data-cam-flash") == 1


def test_card_only_chip_for_support(app_client):
    def page(pat, pwd):
        d = _dvr()
        d.pattern_cipher, d.password_cipher = pat, pwd
        with _ctx(app_client):
            with patch("itcj2.apps.cameras.pages.viewer.dvr_service.list_visible", return_value=[d]):
                return app_client.get("/cameras/", headers=_hdr()).text
    both, only_pat, only_pwd, none = page("a", "b"), page("a", None), page(None, "b"), page(None, None)
    assert "cam-card__only" not in both and "Patrón · Contraseña" not in both
    assert 'cam-card__only">Solo patrón<' in only_pat
    assert 'cam-card__only">Solo contraseña<' in only_pwd
    assert 'cam-card__only">Sin credenciales<' in none


def test_note_before_reveal_button_both_variants(app_client):
    for manage in (True, False):
        v = _viewer(can_manage=manage, see_all=manage, dept_ids=frozenset({1}))
        with _ctx(app_client, viewer=v):
            with patch("itcj2.apps.cameras.pages.viewer.dvr_service.list_visible", return_value=[_dvr()]):
                r = app_client.get("/cameras/", headers=_hdr())
        assert 0 < r.text.index('id="cam-note-1"') < r.text.index('data-cam-reveal="1"')


def test_audit_reveal_labels_from_detail(app_client):
    base = {"id": 1, "dvr_id": 1, "dvr_name": "D", "actor_id": 5, "actor_name": "Ana",
            "created_at": datetime(2026, 11, 13, 9, 5), "action": "reveal"}

    def d(p, w):
        return {"pattern": p, "password": w, "username": False, "notes": False}
    rows = [{**base, "detail": d(True, True)}, {**base, "detail": d(False, True)},
            {**base, "detail": d(True, False)}, {**base, "detail": d(False, False)},
            {**base, "detail": None},
            {**base, "action": "reactivate", "detail": None}]
    with _ctx(app_client, audit_page=dict(return_value=(rows, 6)), audit_actors=dict(return_value=[])):
        r = app_client.get("/cameras/audit", headers=_hdr())
    for txt in ("Vio patrón y contraseña<", "Vio la contraseña<", "Vio el patrón<",
                "Vio el DVR (sin datos guardados)<", "Vio credenciales<", "Reactivó el DVR<"):
        assert txt in r.text, txt
    assert '<option value="reveal">Vio credenciales</option>' in r.text


def test_audit_date_filters_parse_and_ignore_invalid(app_client):
    from datetime import date
    with _ctx(app_client, audit_page=dict(return_value=([], 0)), audit_actors=dict(return_value=[])) as _:
        with patch(f"{S}.audit_page", return_value=([], 0)) as ap:
            r = app_client.get("/cameras/audit?desde=2026-11-01&hasta=2026-11-13", headers=_hdr())
            assert ap.call_args.kwargs["desde"] == date(2026, 11, 1)
            assert ap.call_args.kwargs["hasta"] == date(2026, 11, 13)
            assert 'name="desde" value="2026-11-01"' in r.text and 'hx-push-url="true"' in r.text
            r = app_client.get("/cameras/audit?desde=ayer&hasta=2026-13-45", headers=_hdr())
            assert r.status_code == 200
            assert ap.call_args.kwargs["desde"] is None and ap.call_args.kwargs["hasta"] is None
            assert "ayer" not in r.text


def test_audit_page_dates_inclusive(db_session, cam_world, cameras_key):
    from datetime import date
    from sqlalchemy import text
    from itcj2.apps.cameras.schemas.dvr import DvrInput
    from itcj2.apps.cameras.services import dvr_service as svc
    d = svc.create(db_session, DvrInput(name="Dfecha", password="pw1"), cam_world.tech)
    svc.reveal(db_session, d, cam_world.tech)
    day = db_session.execute(text("select created_at::date from cameras_audit_log where dvr_id=:i limit 1"),
                             {"i": d.id}).scalar()
    kw = dict(page=1, dvr_id=d.id)
    assert svc.audit_page(db_session, desde=day, hasta=day, **kw)[1] == 2  # create + reveal, mismo día
    assert svc.audit_page(db_session, desde=day, **kw)[1] == 2
    assert svc.audit_page(db_session, hasta=day, **kw)[1] == 2
    assert svc.audit_page(db_session, desde=date.fromordinal(day.toordinal() + 1), **kw)[1] == 0
    assert svc.audit_page(db_session, hasta=date.fromordinal(day.toordinal() - 1), **kw)[1] == 0


def test_reveal_logs_boolean_detail_only(db_session, cam_world, cameras_key):
    import json
    from itcj2.apps.cameras.models import CamerasAuditLog
    from itcj2.apps.cameras.schemas.dvr import DvrInput
    from itcj2.apps.cameras.services import dvr_service as svc
    d = svc.create(db_session, DvrInput(name="D", password="Zq9pass", username="adm", notes="nota-secreta"),
                   cam_world.tech)
    svc.reveal(db_session, d, cam_world.tech)
    row = db_session.query(CamerasAuditLog).filter_by(dvr_id=d.id, action="reveal").first()
    assert row.detail == {"pattern": False, "password": True, "username": True, "notes": True}
    blob = json.dumps(row.detail)
    assert "Zq9pass" not in blob and "adm" not in blob and "nota-secreta" not in blob


def test_audit_extreme_dates_are_ignored_not_500(app_client):
    with _ctx(app_client, audit_page=dict(return_value=([], 0)),
              audit_actors=dict(return_value=[])) as _:
        for q in ("hasta=9999-12-31", "desde=0001-01-01", "hasta=9999-01-01"):
            assert app_client.get(f"/cameras/audit?{q}", headers=_hdr()).status_code == 200, q
        assert app_client.get("/cameras/audit?hasta=2026-11-17", headers=_hdr()).status_code == 200


def test_flash_baja_copy_only_links_for_managers(app_client):
    with _ctx(app_client):
        r = app_client.get("/cameras/?ok=baja", headers=_hdr())
    assert "DVR dado de baja." in r.text and "Puedes reactivarlo en" in r.text
    v = _viewer(can_manage=False, can_audit=False, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v):
        r = app_client.get("/cameras/?ok=baja", headers=_hdr())
    assert "DVR dado de baja." in r.text and "Puedes reactivarlo" not in r.text


def test_reactivate_missing_htmx_renders_visible_404_in_row(app_client):
    with _ctx(app_client, get_inactive=dict(return_value=None)):
        r = app_client.post("/cameras/dvrs/9/reactivate", headers={**_hdr(), "HX-Request": "true"})
        assert r.status_code == 404 and "No encontrado." in r.text
        item = {"dvr": _dvr(3), "when": None, "by": None}
    with _ctx(app_client, list_inactive=dict(return_value=[item])):
        page = app_client.get("/cameras/inactive", headers=_hdr()).text
    assert 'hx-target="#cam-inactive-3"' in page and 'hx-swap="innerHTML"' in page and 'hx-disabled-elt="find button"' in page



def test_audit_inverted_dates_are_swapped_and_no_stale_limits(app_client):
    from datetime import date
    with _ctx(app_client, audit_page=dict(return_value=([], 0)), audit_actors=dict(return_value=[])):
        with patch(f"{S}.audit_page", return_value=([], 0)) as ap:
            r = app_client.get("/cameras/audit?desde=2026-11-13&hasta=2026-11-01", headers=_hdr())
    assert ap.call_args.kwargs["desde"] == date(2026, 11, 1) and ap.call_args.kwargs["hasta"] == date(2026, 11, 13)
    assert " min=" not in r.text.split('id="a-hasta"')[1].split(">")[0]
    assert " max=" not in r.text.split('id="a-desde"')[1].split(">")[0]


def test_inactive_and_reactivate_need_see_all(app_client):
    v = _viewer(can_manage=True, see_all=False, dept_ids=frozenset({1}))
    with _ctx(app_client, viewer=v, get_inactive=dict(return_value=_dvr()), list_inactive=dict(return_value=[])):
        assert app_client.get("/cameras/inactive", headers=_hdr()).status_code == 403
        assert app_client.post("/cameras/dvrs/1/reactivate", headers=_hdr()).status_code == 403


def test_card_meta_shows_camera_count_and_type(app_client):
    d = _dvr()
    for t, b, pz, want, absent in (
        ("bala", 6, None, ("6 cámaras", "Bala"), "PTZ"),
        ("ptz", None, 1, ("1 cámara<", "PTZ"), "cámaras<"),
        ("mixtas", 8, 6, ("14 cámaras", "8 bala y 6 PTZ"), "Bala y PTZ"),
        ("bala", None, None, ("Bala",), "cámara"),
    ):
        d.camera_type, d.cameras_bala, d.cameras_ptz = t, b, pz
        with _ctx(app_client):
            with patch(f"{S}.list_visible", return_value=[d]):
                r = app_client.get("/cameras/", headers=_hdr())
        assert "8 canales" in r.text and all(w in r.text for w in want), (t, b, pz)
        assert absent not in r.text.split("8 canales", 1)[1][:200], (t, b, pz)


def test_form_parses_camera_fields_and_overflow_message(app_client):
    with _ctx(app_client):
        with patch(f"{S}.create", return_value=_dvr()) as cr:
            app_client.post("/cameras/dvrs", headers={**_hdr(), "HX-Request": "true"},
                            data={"name": "X", "channels": "8", "camera_type": "mixtas",
                                  "cameras_bala": "4", "cameras_ptz": "2", "password": "p", "password_confirm": "p"})
        got = cr.call_args.args[1]
        assert (got.camera_type, got.cameras_bala, got.cameras_ptz) == ("mixtas", 4, 2)
        for extra, msg in (({"camera_type": "bala", "cameras_bala": "5", "cameras_ptz": "4"},
                            "Hay más cámaras que canales: el DVR tiene 8 canales."),
                           ({"camera_type": "mixtas", "cameras_bala": "5"},
                            "Con Bala y PTZ escribe cuántas hay de cada una.")):
            r = app_client.post("/cameras/dvrs", headers={**_hdr(), "HX-Request": "true"},
                                data={"name": "X", "channels": "8", "password": "p",
                                      "password_confirm": "p", **extra})
            assert r.status_code == 422
            assert unquote(r.headers["x-cam-error"]) in (msg, "Con tipo Bala solo se capturan cámaras bala.")


def test_edit_form_prefills_camera_fields(app_client):
    d = _dvr()
    d.camera_type, d.cameras_bala, d.cameras_ptz = "ptz", None, 0
    with _ctx(app_client, get_visible=dict(return_value=d)):
        r = app_client.get("/cameras/dvrs/1/edit", headers=_hdr())
    assert '<option value="ptz" selected>' in r.text and 'name="cameras_ptz"' in r.text and 'name="cameras_bala"' in r.text
    assert 'name="cameras_ptz" type="number" min="0" max="128" inputmode="numeric" value="0"' in r.text
