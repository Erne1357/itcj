"""profile_service.py:69 — la rama hasattr(icon_class), muerta pre-C4, cobra vida.

Antes de la columna, hasattr(app, 'icon_class') era False → SIEMPRE 'bi-app'.
Con la columna creada, hasattr es True SIEMPRE: hay que garantizar que NULL
siga dando 'bi-app' (no None) y que un valor real se propague.
"""
from itcj2.core.models.app import App
from itcj2.core.models.user import User
from itcj2.core.services.profile_service import get_user_profile_data


def _mk_user(db):
    u = User(first_name="P", last_name="Profile", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_app_icon_null_defaults_bi_app(db_session):
    db_session.add(App(key="prof2", name="Prof2", is_active=True))  # icon_class NULL
    db_session.commit()
    u = _mk_user(db_session)
    data = get_user_profile_data(db_session, u.id)
    assert data["app_assignments"]["prof2"]["app_icon"] == "bi-app"


def test_app_icon_from_db_column(db_session):
    db_session.add(App(key="prof1", name="Prof1", is_active=True, icon_class="bi-rocket"))
    db_session.commit()
    u = _mk_user(db_session)
    data = get_user_profile_data(db_session, u.id)
    assert data["app_assignments"]["prof1"]["app_icon"] == "bi-rocket"
