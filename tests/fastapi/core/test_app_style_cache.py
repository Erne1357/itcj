"""app_style_cache: read-through TTL 60s + invalidación explícita (patrón authz_cache)."""
from itcj2.core.models.app import App
from itcj2.core.services import app_style_cache as cache


def _mk_app(db, key, color="#123456", icon="bi-star"):
    a = App(key=key, name=key, is_active=True, color=color, icon_class=icon)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_styles_read_through(db_session):
    _mk_app(db_session, "asc1", color="#ABCDEF", icon="bi-star")
    cache.invalidate_app_styles()
    try:
        styles = cache.cached_app_styles(db_session)
        assert styles["asc1"] == {"color": "#ABCDEF", "icon_class": "bi-star"}
    finally:
        cache.invalidate_app_styles()  # no dejar datos de test en Redis dev


def test_styles_cached_until_invalidation(db_session):
    a = _mk_app(db_session, "asc2", color="#111111")
    cache.invalidate_app_styles()
    try:
        assert cache.cached_app_styles(db_session)["asc2"]["color"] == "#111111"
        a.color = "#222222"
        db_session.commit()
        # HIT stale intencional: sin invalidar, Redis in-container sirve lo viejo
        assert cache.cached_app_styles(db_session)["asc2"]["color"] == "#111111"
        cache.invalidate_app_styles()
        assert cache.cached_app_styles(db_session)["asc2"]["color"] == "#222222"
    finally:
        cache.invalidate_app_styles()


def test_update_app_endpoint_invalidates(db_session):
    from itcj2.core.api import authz as authz_api
    from itcj2.core.api.authz import AppUpdateBody
    _mk_app(db_session, "asc3", color="#333333")
    cache.invalidate_app_styles()
    try:
        assert cache.cached_app_styles(db_session)["asc3"]["color"] == "#333333"
        authz_api.update_app(app_key="asc3", body=AppUpdateBody(color="#444444"),
                             user={"sub": "1"}, db=db_session)
        # el hook del endpoint invalidó → el siguiente read ve el nuevo valor
        assert cache.cached_app_styles(db_session)["asc3"]["color"] == "#444444"
    finally:
        cache.invalidate_app_styles()
