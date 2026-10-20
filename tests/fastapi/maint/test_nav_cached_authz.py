"""Menú de maint (`_build_maint_nav`) desde el caché de authz.

Perf 2026-10-07: se arma en CADA página de maint y pedía roles y permisos sin
caché (6-10 consultas). Ahora sale de `cached_roles`/`cached_perms`, lo MISMO
que usa la guarda de cada página — así el menú tampoco ofrece lo que un permiso
denegado quita (antes unía directos + por rol sin restar los denegados).
"""
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.maint.pages.nav import _build_maint_nav


def _urls(nav: dict) -> set:
    out = set()
    for item in nav["maint_nav_items"]:
        if item.get("url"):
            out.add(item["url"])
        for sub in item.get("dropdown", []) or item.get("children", []) or []:
            out.add(sub.get("url"))
    return out


@pytest.fixture
def sin_consultas_directas():
    """Las funciones sin caché no deben llamarse desde el menú."""
    def _prohibido(*a, **k):
        raise AssertionError("el menú debe leer roles/permisos del caché de authz")

    with patch("itcj2.core.services.authz_service.user_roles_in_app", side_effect=_prohibido), \
         patch("itcj2.core.services.authz_service.user_direct_perms_in_app", side_effect=_prohibido), \
         patch("itcj2.core.services.authz_service.perms_via_roles", side_effect=_prohibido):
        yield


def _nav(roles, perms):
    with patch("itcj2.core.services.authz_cache.cached_roles", return_value=set(roles)), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set(perms)):
        return _build_maint_nav(10, "/maint/tickets", MagicMock())


def test_el_menu_sale_del_cache(sin_consultas_directas):
    urls = _urls(_nav({"dispatcher"}, {"maint.assignments.page.triage"}))
    assert "/maint/tickets" in urls
    assert "/maint/triage" in urls


def test_un_permiso_ausente_en_el_cache_no_da_el_item(sin_consultas_directas):
    urls = _urls(_nav({"tech_maint"}, set()))
    assert "/maint/triage" not in urls and "/maint/asignacion" not in urls


def test_el_rol_admin_del_cache_abre_todo(sin_consultas_directas):
    urls = _urls(_nav({"admin"}, set()))
    assert {"/maint/triage", "/maint/asignacion"} <= urls
