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


# --- Task 2: sidebar_active derivado en el servidor -------------------------
from pathlib import Path
from unittest.mock import patch

import itcj2


@pytest.fixture()
def admin_role_patch():
    """Simula rol admin@itcj en BD. Punto único: authz_service.user_roles_in_app
    (lo usan _assert_admin pre-F1a y cached_roles post-F1a)."""
    with patch(
        "itcj2.core.services.authz_service.user_roles_in_app",
        return_value={"admin"},
    ):
        yield


def _anchor_tag(html: str, href: str) -> str:
    """Devuelve el tag <a ...> completo cuyo href es exactamente `href`."""
    m = re.search(r'<a\b[^>]*href="' + re.escape(href) + r'"[^>]*>', html)
    assert m, f"no se encontró <a href=\"{href}\"> en el HTML"
    return m.group(0)


class TestNoSidebarSetInTemplates:
    def test_templates_do_not_set_sidebar_active(self):
        base = Path(itcj2.__file__).parent / "core" / "templates" / "core" / "config"
        offenders = [
            str(p)
            for p in base.rglob("*.html")
            if "set sidebar_active" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []


class TestSidebarActiveDerived:
    def test_roles_page_highlights_roles_link(self, app_client, auth_headers, admin_role_patch):
        resp = app_client.get("/itcj/config/roles", headers=auth_headers)
        assert resp.status_code == 200
        assert "active" in _anchor_tag(resp.text, "/itcj/config/roles")
        assert "active" not in _anchor_tag(resp.text, "/itcj/config/apps")

    def test_permissions_page_highlights_apps_link(self, app_client, auth_headers, admin_role_patch):
        resp = app_client.get("/itcj/config/apps/helpdesk/permissions", headers=auth_headers)
        assert resp.status_code == 200
        assert "active" in _anchor_tag(resp.text, "/itcj/config/apps")

    def test_tasks_page_highlights_tasks_link(self, app_client, auth_headers, admin_role_patch):
        resp = app_client.get("/itcj/config/system/tasks", headers=auth_headers)
        assert resp.status_code == 200
        assert "active" in _anchor_tag(resp.text, "/itcj/config/system/tasks")


# --- Task 3: shell HTMX ------------------------------------------------------
class TestHtmxShell:
    def test_cfg_main_and_htmx_stack_present(self, app_client, auth_headers, admin_role_patch):
        resp = app_client.get("/itcj/config", headers=auth_headers)
        assert resp.status_code == 200
        html = resp.text
        assert 'id="cfgMain"' in html
        assert 'data-cfg-page="index"' in html
        assert 'hx-ext="morph,head-support"' in html
        assert 'hx-swap="morph:innerHTML"' in html
        assert 'hx-target="body"' in html
        assert "htmx.org@2.0.3" in html
        assert "idiomorph@0.7.3/dist/idiomorph-ext.min.js" in html
        assert "htmx-ext-head-support@2.0.4/head-support.js" in html
        # los 3 CDN htmx llevan SRI (D9: helpdesk no le puso SRI a idiomorph; aquí sí va)
        assert html.count('integrity="sha384-') >= 3

    def test_page_key_per_page(self, app_client, auth_headers, admin_role_patch):
        resp = app_client.get("/itcj/config/users", headers=auth_headers)
        assert 'data-cfg-page="users"' in resp.text

    def test_boost_island_only_on_registered_targets(self, app_client, auth_headers, admin_role_patch):
        # index está migrada: sus links a index (brand/panel/breadcrumb) van boosteados
        resp = app_client.get("/itcj/config", headers=auth_headers)
        html = resp.text
        assert re.search(r'<a\b[^>]*href="/itcj/config"[^>]*hx-boost="true"', html)
        # users está migrada (F4 Task 2): su link SÍ lleva boost
        assert re.search(r'<a\b[^>]*href="/itcj/config/users"[^>]*hx-boost="true"', html)
        # departments está migrada (F5): su link SÍ lleva boost
        assert re.search(r'<a\b[^>]*href="/itcj/config/departments"[^>]*hx-boost="true"', html)
        # el content-root anuncia los módulos del index
        assert "active-users.js" in html
        # socket.io ahora es vendored y lo provee el shell (config_base.html base
        # scripts), no un CDN ni un módulo del registry (D9, F6 Task 5/6/7).
        assert "js/vendor/socket.io.min.js" in html

    def test_all_12_pages_boostable(self):
        # F5 cerró la migración (departments, department_detail, position_detail):
        # ya no queda ninguna de las 12 páginas de config fuera de
        # CONFIG_PAGE_MODULES. El caso "página NO migrada" ya no existe DENTRO
        # del registry de config; se cubre abajo con una URL fuera de él.
        assert set(nav_config.CONFIG_PAGE_MODULES) == ALL_PAGE_KEYS
        for url in nav_config.ENDPOINT_TO_PAGE:
            probe = url.format(app_key="helpdesk", user_id=1, department_id=1, position_id=1)
            assert nav_config.is_boostable_url(probe) is True, probe

    def test_kill_switch_removes_boost_from_rendered_page(
        self, app_client, auth_headers, admin_role_patch, monkeypatch
    ):
        # Rama solo alcanzable por el kill-switch global: con CONFIG_BOOST_ENABLED
        # = False, una página MIGRADA (index) se renderiza SIN ningún hx-boost y
        # con el boost apagado (data-cfg-boost-urls vacío). Complementa el test
        # unitario TestBoostIsland.test_kill_switch_disables_everything.
        monkeypatch.setattr(nav_config, "CONFIG_BOOST_ENABLED", False)
        resp = app_client.get("/itcj/config", headers=auth_headers)
        assert resp.status_code == 200
        html = resp.text
        assert "hx-boost" not in html          # ningún link del sidebar boostea
        assert 'data-cfg-boost-urls=""' in html  # whitelist de boost vacía (off)

    def test_non_config_url_not_boostable(self):
        # /itcj/profile es una página real del core pero ajena al shell de
        # config: no está (ni debe estar) en ENDPOINT_TO_PAGE. El fallback
        # duro de is_boostable_url/navigate() sigue vigente para destinos
        # fuera de la whitelist de config, aunque las 12 internas ya migraron.
        assert nav_config.is_boostable_url("/itcj/profile") is False
