"""Servicio de DVR: cifrado, scope por departamento y bitácora."""
import json

import pytest

from itcj2.apps.cameras.models import CamerasAuditLog, Dvr
from itcj2.apps.cameras.schemas.dvr import DvrInput
from itcj2.apps.cameras.services import dvr_service as svc


def inp(**kw):
    kw.setdefault("name", "DVR 1")
    return DvrInput(**kw)


def viewer(uid=1, see_all=False, depts=(), manage=False, pwd=False, audit=False):
    return svc.Viewer(uid, see_all, frozenset(depts), manage, pwd, audit)


def actions(db, dvr):
    return [r.action for r in db.query(CamerasAuditLog).filter_by(dvr_id=dvr.id).order_by(CamerasAuditLog.id)]


def test_create_requires_secret(db_session, cam_world, cameras_key):
    with pytest.raises(ValueError):
        svc.create(db_session, inp(), cam_world.tech)


def test_ciphertext_not_plain(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="S3cret!"), cam_world.tech)
    assert "S3cret!" not in d.password_cipher


def test_password_roundtrip_exact(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="  a b  "), cam_world.tech)
    assert svc.reveal(db_session, d, cam_world.tech).password == "  a b  "


def test_head_sees_only_linked(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="x", department_ids=[w.dept_a]), w.tech)
    assert d in svc.list_visible(db_session, viewer(depts={w.dept_a}))
    assert svc.list_visible(db_session, viewer(depts={w.dept_b})) == []
    assert svc.list_visible(db_session, viewer(depts={w.dept_a1})) == []
    assert svc.get_visible(db_session, viewer(depts={w.dept_b}), d.id) is None
    assert svc.get_visible(db_session, viewer(depts={w.dept_a}), d.id) is d


def test_shared_dvr_password_visible_to_other_head(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="old", department_ids=[w.dept_a, w.dept_b]), w.tech)
    assert svc.set_password(db_session, viewer(w.head_a, depts={w.dept_a}, pwd=True), d.id, "nueva", w.head_a)
    r = svc.reveal(db_session, d, w.head_b)
    assert r.password == "nueva"
    assert r.password_changed_by == "Cam head_a"
    with pytest.raises(ValueError):
        svc.set_password(db_session, viewer(w.head_a, depts={w.dept_a}, pwd=True), d.id, "", w.head_a)


def test_deactivated_dvr_hidden_and_404(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x", department_ids=[cam_world.dept_a]), cam_world.tech)
    svc.deactivate(db_session, d, cam_world.tech)
    v = viewer(see_all=True)
    assert d not in svc.list_visible(db_session, v)
    assert svc.get_visible(db_session, v, d.id) is None
    assert "deactivate" in actions(db_session, d)


def test_unlinked_dvr_only_staff(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x"), cam_world.tech)
    assert d in svc.list_visible(db_session, viewer(see_all=True))
    assert d not in svc.list_visible(db_session, viewer(depts={cam_world.dept_a}))


def test_reveal_logs_without_secrets(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="Zq9pass", pattern="1-3-5-7", username="adm",
                                   notes="nota"), cam_world.tech)
    svc.reveal(db_session, d, cam_world.tech)
    last = db_session.query(CamerasAuditLog).order_by(CamerasAuditLog.id.desc()).first()
    assert last.action == "reveal"
    blob = json.dumps([r.detail for r in db_session.query(CamerasAuditLog).all()])
    assert "Zq9pass" not in blob and "1357" not in blob and "nota" not in blob


def test_update_keeps_secret_when_blank(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x", pattern="1357"), cam_world.tech)
    before = d.password_cipher
    svc.update(db_session, d, inp(name="Otro", password=None), cam_world.tech)
    assert d.password_cipher == before and d.pattern_cipher
    svc.update(db_session, d, inp(name="Otro", remove_pattern=True), cam_world.tech)
    assert d.pattern_cipher is None
    assert {"update", "pattern_update"} <= set(actions(db_session, d))


def test_search_q(db_session, cam_world, cameras_key):
    w = cam_world
    d1 = svc.create(db_session, inp(name="Uno", location="Edificio K", password="x"), w.tech)
    d2 = svc.create(db_session, inp(name="Dos", password="x", department_ids=[w.dept_a]), w.tech)
    v = viewer(see_all=True)
    assert svc.list_visible(db_session, v, q="edificio") == [d1]
    assert svc.list_visible(db_session, v, q="cam_a") == [d2]


def test_viewer_for_head_real(db_session, cam_world, cameras_key):
    from itcj2.core.services import authz_cache
    authz_cache.invalidate_user(cam_world.head_a)
    v = svc.viewer_for(db_session, {"sub": str(cam_world.head_a), "role": "staff"})
    assert v.dept_ids == {cam_world.dept_a}
    assert v.can_update_password and not v.can_manage and not v.see_all


def test_set_password_scope_enforced(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="old", department_ids=[w.dept_a]), w.tech)
    assert svc.set_password(db_session, viewer(w.head_b, depts={w.dept_b}, pwd=True), d.id, "x", w.head_b) is False
    assert "password_update" not in actions(db_session, d)
    assert svc.set_password(db_session, viewer(w.head_a, depts={w.dept_a}, pwd=True), d.id, "x", w.head_a) is True
    assert "password_update" in actions(db_session, d)


def test_update_write_only_username_notes(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x", username="adm", notes="n"), cam_world.tech)
    svc.update(db_session, d, inp(name="Otro"), cam_world.tech)
    assert d.username == "adm" and d.notes == "n"
    svc.update(db_session, d, inp(name="Otro", remove_notes=True), cam_world.tech)
    assert d.notes is None and d.username == "adm"


def test_input_error_hides_value():
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as e:
        inp(username="u" * 51)
    assert "u" * 51 not in str(e.value)


def test_repr_hides_secrets(db_session, cam_world, cameras_key):
    assert "Zq9pass" not in repr(inp(password="Zq9pass"))
    d = svc.create(db_session, inp(password="Zq9pass"), cam_world.tech)
    assert "Zq9pass" not in repr(svc.reveal(db_session, d, cam_world.tech))


def test_update_validates_before_mutating(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(name="Orig", password="x"), cam_world.tech)
    with pytest.raises(ValueError):
        svc.update(db_session, d, inp(name="Nuevo", pattern="11"), cam_world.tech)
    assert d.name == "Orig"
    assert "update" not in actions(db_session, d)


def test_reveal_pattern_only_has_no_changed_by(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(pattern="1357"), cam_world.tech)
    r = svc.reveal(db_session, d, cam_world.tech)
    assert r.password is None and r.password_changed_at is None and r.password_changed_by is None


def test_create_without_key_leaves_no_row(db_session, cam_world, monkeypatch):
    from itcj2.apps.cameras.services import secrets as sec
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "CAMERAS_SECRET_KEY", None)
    n = db_session.query(Dvr).count()
    with pytest.raises(sec.CamerasKeyMissing):
        svc.create(db_session, inp(password="x"), cam_world.tech)
    assert db_session.query(Dvr).count() == n


def test_remove_password_and_departments_update(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="x", pattern="1357", department_ids=[w.dept_a]), w.tech)
    svc.update(db_session, d, inp(remove_password=True, department_ids=[w.dept_a, w.dept_b]), w.tech)
    assert d.password_cipher is None
    assert "password_update" in actions(db_session, d)
    row = (db_session.query(CamerasAuditLog).filter_by(dvr_id=d.id, action="departments_update").one())
    assert row.detail == {"departments": sorted([w.dept_a, w.dept_b])}


def test_update_cannot_remove_last_secret(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="pw1", pattern="1259"), w.tech)
    pw, pat = d.password_cipher, d.pattern_cipher
    with pytest.raises(ValueError, match="al menos"):
        svc.update(db_session, d, inp(remove_password=True, remove_pattern=True), w.tech)
    db_session.refresh(d)
    assert d.password_cipher == pw and d.pattern_cipher == pat


def test_shared_dvr_listed_for_head_b(db_session, cam_world, cameras_key):
    w = cam_world
    d = svc.create(db_session, inp(password="pw1", department_ids=[w.dept_a, w.dept_b]), w.tech)
    assert d in svc.list_visible(db_session, viewer(w.head_b, depts={w.dept_b}))


def _dvr_with_pw(db, cam_world, name="D"):
    return svc.create(db, inp(name=name, password="pw1"), cam_world.tech)


def test_extend_without_reveal_refused_no_row(db_session, cam_world, cameras_key):
    d = _dvr_with_pw(db_session, cam_world)
    before = actions(db_session, d)
    with pytest.raises(ValueError, match="Vuelve a revelar"):
        svc.extend(db_session, d, cam_world.tech)
    assert actions(db_session, d) == before


def test_extend_after_other_dvr_reveal_refused(db_session, cam_world, cameras_key):
    d1 = _dvr_with_pw(db_session, cam_world, "D1")
    d2 = _dvr_with_pw(db_session, cam_world, "D2")
    svc.reveal(db_session, d2, cam_world.tech)
    with pytest.raises(ValueError):
        svc.extend(db_session, d1, cam_world.tech)
    assert "extend" not in actions(db_session, d1)


def test_extend_reveal_older_than_window_refused(db_session, cam_world, cameras_key):
    from datetime import timedelta
    from sqlalchemy import func
    d = _dvr_with_pw(db_session, cam_world)
    db_session.add(CamerasAuditLog(dvr_id=d.id, dvr_name=d.name, actor_id=cam_world.tech,
                                   action="reveal", created_at=func.now() - timedelta(minutes=11)))
    db_session.commit()
    with pytest.raises(ValueError):
        svc.extend(db_session, d, cam_world.tech)
    assert "extend" not in actions(db_session, d)


def test_extend_reveal_within_window_allowed(db_session, cam_world, cameras_key):
    from datetime import timedelta
    from sqlalchemy import func
    d = _dvr_with_pw(db_session, cam_world)
    db_session.add(CamerasAuditLog(dvr_id=d.id, dvr_name=d.name, actor_id=cam_world.tech,
                                   action="reveal", created_at=func.now() - timedelta(minutes=9)))
    db_session.commit()
    svc.extend(db_session, d, cam_world.tech)
    assert actions(db_session, d)[-1] == "extend"


def test_extend_eleventh_after_reveal_refused(db_session, cam_world, cameras_key):
    d = _dvr_with_pw(db_session, cam_world)
    svc.reveal(db_session, d, cam_world.tech)
    for _ in range(10):
        svc.extend(db_session, d, cam_world.tech)
    before = actions(db_session, d)
    with pytest.raises(ValueError):
        svc.extend(db_session, d, cam_world.tech)
    assert actions(db_session, d) == before
    svc.reveal(db_session, d, cam_world.tech)
    svc.extend(db_session, d, cam_world.tech)


def test_viewer_for_ignores_global_admin_role(db_session, cam_world, cameras_key):
    from itcj2.core.services import authz_cache
    authz_cache.invalidate_user(cam_world.nobody)
    v = svc.viewer_for(db_session, {"sub": str(cam_world.nobody), "role": "admin"})
    assert not (v.see_all or v.can_manage or v.can_update_password or v.can_audit) and not v.dept_ids


def test_global_admin_with_department_head_sees_only_its_department(db_session, cam_world, cameras_key):
    from itcj2.core.services import authz_cache
    w = cam_world
    d_a = svc.create(db_session, inp(name="A", password="x", department_ids=[w.dept_a]), w.tech)
    svc.create(db_session, inp(name="B", password="x", department_ids=[w.dept_b]), w.tech)
    authz_cache.invalidate_user(w.head_a)
    v = svc.viewer_for(db_session, {"sub": str(w.head_a), "role": "admin"})
    assert not v.see_all and not v.can_manage
    assert svc.list_visible(db_session, v) == [d_a]


def test_app_admin_role_without_global_admin_sees_and_manages_all(db_session, cam_world, cameras_key):
    from itcj2.core.models.role import Role
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.services import authz_cache
    w = cam_world
    db_session.add(UserAppRole(user_id=w.nobody, app_id=w.app_id,
                               role_id=db_session.query(Role).filter_by(name="admin").one().id))
    db_session.commit()
    authz_cache.invalidate_user(w.nobody)
    d1 = svc.create(db_session, inp(name="A", password="x", department_ids=[w.dept_a]), w.tech)
    d2 = svc.create(db_session, inp(name="B", password="x", department_ids=[w.dept_b]), w.tech)
    v = svc.viewer_for(db_session, {"sub": str(w.nobody), "role": "staff"})
    assert v.see_all and v.can_manage
    assert set(svc.list_visible(db_session, v)) == {d1, d2}


# --- buscador: marca, modelo, canales -------------------------------------

def _search_world(db, w):
    mk = lambda **kw: svc.create(db, inp(password="x", **kw), w.tech)
    return SimpleNamespaceX(
        h8=mk(name="Alfa", brand="Hikvision", model="DS-7208", channels=8, department_ids=[w.dept_a]),
        h16=mk(name="Beta", brand="Hikvision", model="DS-7216", channels=16),
        d8=mk(name="Gama", brand="Dahua", model="XVR5108HS", channels=8),
        d16=mk(name="Delta", brand="Dahua", model="XVR5216", channels=16),
        ed=mk(name="Edificio 8", brand="Dahua", model="XVR5116", channels=16),
        pct=mk(name="Cien%", brand="Dahua", model="Q_1", channels=4),
    )


class SimpleNamespaceX:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _s(db, q, **vkw):
    return set(svc.list_visible(db, viewer(**(vkw or {"see_all": True})), q=q))


def test_search_brand_case_insensitive_and_partial(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    assert _s(db_session, "Hikvision") == {x.h8, x.h16}
    assert _s(db_session, "HIK") == {x.h8, x.h16}


def test_search_channels_number_not_model_substring(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    # h16 tiene «8» en el modelo (DS-7208 es h8; XVR5108HS es d8) y «Edificio 8» lo trae en el nombre
    assert _s(db_session, "8") == {x.h8, x.d8, x.ed}
    assert _s(db_session, "8 canales") == {x.h8, x.d8, x.ed}
    assert _s(db_session, "16 CANALES") == {x.h16, x.d16, x.ed}


def test_search_and_between_words(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    assert _s(db_session, "hikvision 8 canales") == {x.h8}


def test_search_by_model(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    assert _s(db_session, "DS-7208") == {x.h8}
    assert _s(db_session, "xvr5108hs") == {x.d8}


def test_search_only_filler_is_no_filter(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    assert _s(db_session, "canales") == _s(db_session, "") == _s(db_session, None)
    assert x.h8 in _s(db_session, "Cámaras")


def test_search_wildcards_are_literal(db_session, cam_world, cameras_key):
    x = _search_world(db_session, cam_world)
    assert _s(db_session, "%") == {x.pct}
    assert _s(db_session, "q_1") == {x.pct}
    assert _s(db_session, "h_") == set()  # «_» no comodina («Hikvision» no cuenta)
    assert _s(db_session, "100%") == set()


def test_search_department_and_scope(db_session, cam_world, cameras_key):
    w = cam_world
    x = _search_world(db_session, w)
    assert _s(db_session, "cam_a") == {x.h8}
    # un jefe de dept_b no ve el DVR de dept_a aunque coincida
    assert _s(db_session, "Hikvision", depts={w.dept_b}) == set()
    assert _s(db_session, "Hikvision", depts={w.dept_a}) == {x.h8}


# --- tipo y cantidad de cámaras ---

def test_camera_type_and_count_create_and_blank(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x", channels=8, camera_type="ptz", cameras_ptz=6), cam_world.tech)
    assert (d.camera_type, d.cameras_bala, d.cameras_ptz) == ("ptz", None, 6)
    m = svc.create(db_session, inp(name="M", password="x", channels=20, camera_type="mixtas",
                                   cameras_bala=8, cameras_ptz=6), cam_world.tech)
    assert (m.cameras_bala, m.cameras_ptz) == (8, 6)
    blank = inp(password="x", camera_type="")
    assert blank.camera_type is None and blank.cameras_bala is None and blank.cameras_ptz is None


@pytest.mark.parametrize("kw, msg", [
    (dict(camera_type="mixtas", cameras_bala=3), "Con Bala y PTZ escribe cuántas hay de cada una."),
    (dict(camera_type="mixtas", cameras_bala=3, cameras_ptz=0), "Con Bala y PTZ escribe cuántas hay de cada una."),
    (dict(camera_type="mixtas"), "Con Bala y PTZ escribe cuántas hay de cada una."),
    (dict(camera_type="bala", cameras_ptz=2), "Con tipo Bala solo se capturan cámaras bala."),
    (dict(camera_type="ptz", cameras_bala=2), "Con tipo PTZ solo se capturan cámaras PTZ."),
    (dict(cameras_bala=2), "Elige el tipo de cámaras."),
    (dict(cameras_ptz=2), "Elige el tipo de cámaras."),
    (dict(channels=8, camera_type="mixtas", cameras_bala=5, cameras_ptz=4),
     "Hay más cámaras que canales: el DVR tiene 8 canales."),
    (dict(channels=8, camera_type="bala", cameras_bala=9),
     "Hay más cámaras que canales: el DVR tiene 8 canales."),
])
def test_camera_count_rules_reject(kw, msg):
    with pytest.raises(ValueError, match=msg):
        inp(**kw)


def test_camera_count_rules_accept():
    assert inp(channels=8, camera_type="bala", cameras_bala=8).cameras_bala == 8
    assert inp(camera_type="ptz", cameras_ptz=0).cameras_ptz == 0
    assert inp(camera_type="bala").cameras_bala is None
    assert inp(camera_type="mixtas", cameras_bala=1, cameras_ptz=127).cameras_ptz == 127
    for kw in (dict(camera_type="bala", cameras_bala=129), dict(camera_type="domo")):
        with pytest.raises(ValueError):
            inp(**kw)


def test_update_camera_fields_logged_and_cleared(db_session, cam_world, cameras_key):
    d = svc.create(db_session, inp(password="x", channels=8), cam_world.tech)
    svc.update(db_session, d, inp(channels=8, camera_type="mixtas", cameras_bala=4, cameras_ptz=2), cam_world.tech)
    log = db_session.query(CamerasAuditLog).filter_by(dvr_id=d.id, action="update").one()
    assert set(log.detail["fields"]) == {"camera_type", "cameras_bala", "cameras_ptz"}
    svc.update(db_session, d, inp(channels=8), cam_world.tech)
    assert d.camera_type is None and d.cameras_bala is None and d.cameras_ptz is None


def test_search_by_camera_type(db_session, cam_world, cameras_key):
    a = svc.create(db_session, inp(name="A", password="x", camera_type="ptz"), cam_world.tech)
    b = svc.create(db_session, inp(name="B", password="x", camera_type="bala"), cam_world.tech)
    c = svc.create(db_session, inp(name="C", password="x", camera_type="mixtas", channels=4, cameras_bala=2, cameras_ptz=2), cam_world.tech)
    v = viewer(see_all=True)
    assert set(svc.list_visible(db_session, v, q="PTZ")) == {a, c}
    assert set(svc.list_visible(db_session, v, q="bala")) == {b, c}
    assert svc.list_visible(db_session, v, q="mixtas") == [c]
    assert svc.list_visible(db_session, v, q="4") == [c]  # números siguen siendo canales
