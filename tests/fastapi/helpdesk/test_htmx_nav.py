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


PILOT = [
    ("/help-desk/admin/home", "admin_home"),
    ("/help-desk/admin/tickets-list", "admin_tickets_list"),
    ("/help-desk/admin/categories", "admin_categories"),
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
    assert 'hx-ext="morph"' in html
