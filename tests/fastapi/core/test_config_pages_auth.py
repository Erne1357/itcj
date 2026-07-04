"""F1a: /itcj/config usa require_page_roles("itcj", ["admin"]) + DbSession.

- El guard admin debe resolverse vía authz_cache.cached_roles (dependencia
  require_page_roles), NO vía el legacy _assert_admin (user_roles_in_app +
  SessionLocal manual, config.py:42-73 pre-F1a).
- Los handlers deben consumir la dependencia get_db (override-able), NO abrir
  SessionLocal() a mano.
"""
from unittest.mock import MagicMock, patch

import pytest

from itcj2.database import get_db

CONFIG_URLS = [
    "/itcj/config",
    "/itcj/config/apps",
    "/itcj/config/roles",
    "/itcj/config/apps/helpdesk/permissions",
    "/itcj/config/themes",
    "/itcj/config/users",
    "/itcj/config/users/1",
    "/itcj/config/departments",
    "/itcj/config/departments/1",
    "/itcj/config/positions/1",
    "/itcj/config/email",
    "/itcj/config/email/auth/login",
    "/itcj/config/system/tasks",
]


class TestAdminGuardViaRequirePageRoles:
    def test_admin_check_goes_through_cached_roles(self, app_client, auth_headers):
        """cached_roles={'admin'} -> 200, SIN pisar el camino legacy
        (user_roles_in_app directo explota si alguien lo llama)."""
        with patch("itcj2.core.services.authz_cache.cached_roles",
                   return_value={"admin"}), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   side_effect=AssertionError("legacy _assert_admin path used")):
            resp = app_client.get("/itcj/config/themes", headers=auth_headers)
        assert resp.status_code == 200

    def test_handlers_use_get_db_dependency(self, app_client, auth_headers):
        """El handler consume get_db (override) y NO abre SessionLocal() manual
        (patcheado para explotar)."""
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = []

        def override_get_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("itcj2.core.services.authz_cache.cached_roles",
                       return_value={"admin"}), \
                 patch("itcj2.database.SessionLocal",
                       side_effect=AssertionError("manual SessionLocal in page handler")):
                resp = app_client.get("/itcj/config/apps", headers=auth_headers)
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)
        assert resp.status_code == 200

    def test_non_admin_gets_403(self, app_client, auth_headers):
        with patch("itcj2.core.services.authz_cache.cached_roles",
                   return_value={"staff"}), \
             patch("itcj2.core.services.authz_cache.cached_has_assignment",
                   return_value=False):
            resp = app_client.get("/itcj/config/themes", headers=auth_headers)
        assert resp.status_code == 403

    @pytest.mark.parametrize("url", CONFIG_URLS)
    def test_unauthenticated_redirects_to_login(self, app_client, url):
        resp = app_client.get(url, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/itcj/login"
