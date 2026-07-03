"""Notification.to_dict: icon DB-driven + app_color_hex aditivo (F1b-D1: sin flip de app_color)."""
from itcj2.core.models.app import App
from itcj2.core.models.notification import Notification
from itcj2.core.models.user import User
from itcj2.core.services.app_style_cache import invalidate_app_styles


def _mk_notif(db, app_name):
    u = User(first_name="N", last_name="Notif", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    n = Notification(user_id=u.id, app_name=app_name, type="SYSTEM", title="t", data={})
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def test_icon_and_hex_from_db(db_session):
    db_session.add(App(key="ntfy1", name="N1", is_active=True,
                       color="#ABC123", icon_class="bi-rocket"))
    db_session.commit()
    invalidate_app_styles()
    try:
        d = _mk_notif(db_session, "ntfy1").to_dict()
        assert d["app_icon"] == "bi-rocket"
        assert d["app_color_hex"] == "#ABC123"
    finally:
        invalidate_app_styles()


def test_app_color_keeps_legacy_tone(db_session):
    # PIN de no-ruptura F1b-D1: los widgets renderizan `bg-${app_color}` como
    # CLASE Bootstrap; app_color NO debe volverse hex hasta F6.
    db_session.add(App(key="tone1", name="T", is_active=True, color="#198754"))
    db_session.commit()
    invalidate_app_styles()
    try:
        d = _mk_notif(db_session, "tone1").to_dict()
        assert not str(d["app_color"]).startswith("#")
    finally:
        invalidate_app_styles()


def test_unknown_app_falls_back_legacy(db_session):
    invalidate_app_styles()
    try:
        d = _mk_notif(db_session, "noapp_xyz").to_dict()
        assert d["app_icon"] == "bi-bell"
        assert d["app_color"] == "info"
        assert d["app_color_hex"] is None
    finally:
        invalidate_app_styles()


def test_db_icon_null_falls_back_legacy_map(db_session):
    # App en BD pero icon_class NULL y sin entrada legacy → default bi-bell.
    db_session.add(App(key="nullicon1", name="NI", is_active=True))
    db_session.commit()
    invalidate_app_styles()
    try:
        d = _mk_notif(db_session, "nullicon1").to_dict()
        assert d["app_icon"] == "bi-bell"
    finally:
        invalidate_app_styles()
