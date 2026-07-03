"""Tests del shell HTMX de /itcj/config (fase F2).

Task 1: unit tests del registry nav_config (contrato C1).
Tasks 2/3/6 agregan tests de integración HTTP en este mismo archivo.
"""
import re

import pytest

from itcj2.core.pages import nav_config

ALL_PAGE_KEYS = {
    "index", "apps", "roles", "permissions", "themes", "tasks", "email",
    "users", "user_detail", "departments", "department_detail", "position_detail",
}


class TestSidebarByPage:
    def test_all_12_page_keys_mapped(self):
        assert set(nav_config.SIDEBAR_BY_PAGE) == ALL_PAGE_KEYS

    def test_detail_pages_highlight_parent_entry(self):
        assert nav_config.SIDEBAR_BY_PAGE["index"] == "dashboard"
        assert nav_config.SIDEBAR_BY_PAGE["permissions"] == "apps"
        assert nav_config.SIDEBAR_BY_PAGE["user_detail"] == "users"
        assert nav_config.SIDEBAR_BY_PAGE["department_detail"] == "departments"
        assert nav_config.SIDEBAR_BY_PAGE["position_detail"] == "departments"


class TestUrlToPage:
    @pytest.mark.parametrize("url,page", [
        ("/itcj/config", "index"),
        ("/itcj/config/roles", "roles"),
        ("/itcj/config/apps/helpdesk/permissions", "permissions"),
        ("/itcj/config/users", "users"),
        ("/itcj/config/users?page=2&q=x", "users"),
        ("/itcj/config/users/42", "user_detail"),
        ("/itcj/config/departments/7", "department_detail"),
        ("/itcj/config/positions/7", "position_detail"),
        ("/itcj/config/system/tasks", "tasks"),
    ])
    def test_resolves(self, url, page):
        assert nav_config.url_to_page(url) == page

    def test_unknown_urls_are_none(self):
        assert nav_config.url_to_page("/help-desk/admin/home") is None
        assert nav_config.url_to_page("/itcj/config/email/auth/login") is None
        assert nav_config.url_to_page("") is None


class TestBoostIsland:
    def test_unregistered_page_not_boostable(self, monkeypatch):
        monkeypatch.setattr(nav_config, "CONFIG_PAGE_MODULES", {})
        assert nav_config.is_boostable_url("/itcj/config") is False
        assert nav_config.boost_urls_regex() == ""

    def test_registered_pages_boostable(self, monkeypatch):
        monkeypatch.setattr(nav_config, "CONFIG_PAGE_MODULES", {"index": [], "roles": []})
        assert nav_config.is_boostable_url("/itcj/config") is True
        assert nav_config.is_boostable_url("/itcj/config/roles") is True
        assert nav_config.is_boostable_url("/itcj/config/users") is False
        rx = nav_config.boost_urls_regex()
        assert re.match(rx, "/itcj/config")
        assert re.match(rx, "/itcj/config/roles")
        assert not re.fullmatch("(?:" + rx + ")", "/itcj/config/users")

    def test_kill_switch_disables_everything(self, monkeypatch):
        monkeypatch.setattr(nav_config, "CONFIG_PAGE_MODULES", {"index": []})
        monkeypatch.setattr(nav_config, "CONFIG_BOOST_ENABLED", False)
        assert nav_config.is_boostable_url("/itcj/config") is False
        assert nav_config.boost_urls_regex() == ""


class TestModuleUrl:
    def test_local_path_versioned_with_sv(self):
        url = nav_config._module_url("js/config/active-users.js")
        assert url.startswith("/static/core/js/config/active-users.js?v=")

    def test_cdn_url_passthrough(self):
        cdn = "https://cdn.socket.io/4.7.5/socket.io.min.js"
        assert nav_config._module_url(cdn) == cdn
