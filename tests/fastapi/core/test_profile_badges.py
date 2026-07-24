"""F7 (spec 3.8 / D7): profile app assignments expose DB-driven color/icon."""
from itcj2.core.models.app import App
from itcj2.core.models.user import User
from itcj2.core.services.profile_service import get_user_profile_data


def _user(db):
    u = User(first_name="Badge", last_name="Probe", is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_app_assignments_use_db_color_and_icon(db_session):
    user = _user(db_session)
    app = App(key="zzbadgeapp", name="Badge App", is_active=True,
              color="#123456", icon_class="bi-rocket")
    db_session.add(app); db_session.commit()

    profile = get_user_profile_data(db_session, user.id)
    entry = profile["app_assignments"]["zzbadgeapp"]
    assert entry["app_icon"] == "bi-rocket"
    assert entry["app_color"] == "#123456"


def test_app_assignments_fallback_when_null(db_session):
    user = _user(db_session)
    app = App(key="zznocolor", name="No Color", is_active=True)
    db_session.add(app); db_session.commit()

    profile = get_user_profile_data(db_session, user.id)
    entry = profile["app_assignments"]["zznocolor"]
    assert entry["app_icon"] == "bi-app"
    assert entry["app_color"] == "#6c757d"
