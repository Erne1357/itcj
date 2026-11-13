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
    svc.set_password(db_session, d, "nueva", w.head_a)
    r = svc.reveal(db_session, d, w.head_b)
    assert r.password == "nueva"
    assert r.password_changed_by == "Cam head_a"
    with pytest.raises(ValueError):
        svc.set_password(db_session, d, "", w.head_a)


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
