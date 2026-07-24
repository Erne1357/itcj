"""Tests de la migración a navegación HTMX (hx-boost + idiomorph) del piloto admin/tickets.

require_page_app NO hace bypass de admin: verifica cached_has_assignment + cached_perms
(BD). Para tests sin BD parcheamos esas dos en su módulo fuente y las funciones de
construcción de nav (authz_service / warehouse_auth).
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.conftest import make_jwt

ADMIN = {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}

# perms que habilitan los items de nav usados + acceso a cada página piloto
NAV_PERMS = {
    "helpdesk.tickets.page.list_all",      # → Gestión > Lista de Tickets (boosteado)
    "helpdesk.assignments.page.list",      # → Gestión > Asignar Tickets (NO boosteado)
    "helpdesk.dashboard.admin",            # → /admin/home
    "helpdesk.categories.page.list",       # → /admin/categories
}


@contextmanager
def patched_authz(perms=NAV_PERMS):
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set(perms)), \
         patch("itcj2.core.services.authz_service.get_user_permissions_for_app", return_value=set(perms)), \
         patch("itcj2.core.services.authz_service.user_roles_in_app", return_value=set()), \
         patch("itcj2.apps.helpdesk.utils.warehouse_auth.get_warehouse_perms_via_helpdesk", return_value=set()):
        yield


# admin/categories ya NO es página HTMX: ahora redirige al tab de Config
# (unificado en config/categories_tab.js). Por eso sale del set de páginas piloto.
PILOT = [
    ("/help-desk/admin/home", "admin_home"),
    ("/help-desk/admin/tickets-list", "admin_tickets_list"),
]


@pytest.mark.parametrize("path,key", PILOT)
def test_pilot_page_has_htmx_assets_and_marker(app_client, path, key):
    with patched_authz():
        resp = app_client.get(path, headers=ADMIN)
    assert resp.status_code == 200
    html = resp.text
    assert "unpkg.com/htmx.org@2.0.3" in html
    assert "idiomorph" in html
    assert f'data-hd-page="{key}"' in html
    # head-support (fusiona el <head> en navegación boosted → CSS por-página)
    assert 'hx-ext="morph,head-support"' in html
    assert "htmx-ext-head-support" in html


def test_admin_categories_redirects_to_config():
    """admin/categories e inventory_categories quedaron unificadas en Config."""
    from itcj2.apps.helpdesk.pages.admin import categories, inventory_categories
    import asyncio

    with patched_authz():
        r1 = asyncio.run(categories(request=None, user={"sub": "200", "role": "admin"}))
        r2 = asyncio.run(inventory_categories(request=None, user={"sub": "200", "role": "admin"}))
    assert r1.status_code == 302 and "/help-desk/admin/config#categorias" in r1.headers["location"]
    assert r2.status_code == 302 and "/help-desk/admin/config#inv-cat" in r2.headers["location"]


def test_nav_marks_only_boosted_endpoints():
    from itcj2.apps.helpdesk.pages.nav import _build_helpdesk_nav
    with patched_authz():
        ctx = _build_helpdesk_nav(user_id=200, current_path="/help-desk/admin/tickets-list")
    flat = []
    for it in ctx["helpdesk_nav_items"]:
        flat.append(it)
        flat += it.get("dropdown", [])
    by_ep = {x.get("endpoint"): x for x in flat}
    assert by_ep["helpdesk_pages.admin_pages.tickets_list"]["hx_boost"] is True
    assert by_ep["helpdesk_pages.admin_pages.assign_tickets"]["hx_boost"] is True


def test_only_boosted_endpoint_link_carries_hx_boost(app_client):
    """En home (página piloto): el link a tickets-list lleva hx-boost; el de
    assign-tickets NO. Valida el scoping "isla" sin pegar a BD de entidades."""
    import re
    with patched_authz():
        resp = app_client.get("/help-desk/admin/home", headers=ADMIN)
    assert resp.status_code == 200
    html = resp.text
    assert 'hx-boost="true"' in html
    # ancla a tickets-list → con boost
    m_list = re.search(r'<a[^>]*tickets-list[^>]*>', html)
    assert m_list and 'hx-boost="true"' in m_list.group(0)
    # ancla a assign-tickets (endpoint ahora boosteado tras migración Fase 2) → con boost
    m_assign = re.search(r'<a[^>]*assign-tickets[^>]*>', html)
    assert m_assign and 'hx-boost="true"' in m_assign.group(0)
