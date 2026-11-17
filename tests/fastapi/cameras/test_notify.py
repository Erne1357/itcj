"""Aviso por la campana cuando un jefe cambia la contraseña de un DVR."""
from itcj2.apps.cameras.models import CamerasAuditLog
from itcj2.apps.cameras.schemas.dvr import DvrInput
from itcj2.apps.cameras.services import dvr_service as svc
from itcj2.core.models.notification import Notification
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole

OLD, NEW = "vieja-Zq81", "nueva-Xk92"


def _user(db, w, tag, role, active=True):
    u = User(first_name=tag, last_name="Aviso", is_active=active)
    db.add(u)
    db.flush()
    db.add(UserAppRole(user_id=u.id, app_id=w.app_id, role_id=db.query(Role).filter_by(name=role).one().id))
    db.commit()
    return u.id


def _setup(db, w):
    admin = _user(db, w, "admin", "admin")
    inactive = _user(db, w, "baja", "tech_soporte", active=False)
    d = svc.create(db, DvrInput(name="DVR Lobby", password=OLD, username="usr-secreto",
                                notes="nota-secreta", department_ids=[w.dept_a, w.dept_b]), w.tech)
    return d, admin, inactive


def _change(db, w, dvr, uid, see_all=False):
    v = svc.Viewer(uid, see_all, frozenset() if see_all else frozenset({w.dept_a}),
                   see_all, not see_all, False)
    return svc.set_password(db, v, dvr.id, NEW, uid)


def _notes(db):
    return db.query(Notification).filter_by(app_name="cameras", type="DVR_PASSWORD_CHANGED").all()


def test_head_change_notifies_viewers_except_actor(db_session, cam_world, cameras_key):
    w = cam_world
    d, admin, inactive = _setup(db_session, w)
    assert _change(db_session, w, d, w.head_a)
    notes = _notes(db_session)
    assert {n.user_id for n in notes} == {w.tech, admin, w.head_b}
    n = notes[0]
    assert n.title == "Cambió la contraseña de un DVR"
    actor = db_session.get(User, w.head_a).full_name
    assert all(x.body == f"DVR Lobby: {actor} la cambió. Revélala en Cámaras cuando la necesites."
               for x in notes)
    assert all(x.data == {"url": f"/cameras/?revelar={d.id}", "dvr_id": d.id} for x in notes)


def test_no_secret_in_notification(db_session, cam_world, cameras_key):
    w = cam_world
    d, _, _ = _setup(db_session, w)
    _change(db_session, w, d, w.head_a)
    for n in _notes(db_session):
        blob = f"{n.title}|{n.body}|{n.data}"
        for secret in (OLD, NEW, "usr-secreto", "nota-secreta"):
            assert secret not in blob


def test_see_all_change_does_not_notify(db_session, cam_world, cameras_key):
    w = cam_world
    d, _, _ = _setup(db_session, w)
    assert _change(db_session, w, d, w.tech, see_all=True)
    assert _notes(db_session) == []


def test_notify_failure_keeps_password_change(db_session, cam_world, cameras_key, monkeypatch):
    from itcj2.core.services.notification_service import NotificationService

    def boom(*a, **k):
        raise RuntimeError("socket caido")
    monkeypatch.setattr(NotificationService, "create", boom)
    w = cam_world
    d, _, _ = _setup(db_session, w)
    assert _change(db_session, w, d, w.head_a)
    assert svc.reveal(db_session, d, w.tech).password == NEW
    assert db_session.query(CamerasAuditLog).filter_by(
        dvr_id=d.id, action="password_update").count() == 1


def test_global_admin_without_cameras_assignment_not_notified(db_session, cam_world, cameras_key):
    from itcj2.core.models.role import Role
    w = cam_world
    d, _, _ = _setup(db_session, w)
    gadmin = User(first_name="gadmin", last_name="Aviso", is_active=True,
                  role_id=db_session.query(Role).filter_by(name="admin").one().id)
    db_session.add(gadmin)
    db_session.commit()
    assert _change(db_session, w, d, w.head_a)
    assert gadmin.id not in {n.user_id for n in _notes(db_session)}
