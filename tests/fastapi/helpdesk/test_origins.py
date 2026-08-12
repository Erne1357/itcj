"""Registro de orígenes de navegación (botón "Volver").

El valor de estos tests es detectar un destino renombrado: el shim `url_for` del
proyecto degrada una clave inválida a `href="#"` sin avisar, que es exactamente
como los ocho casos del `switch` viejo acabaron apuntando a rutas inexistentes.
"""
import itcj2.models  # noqa: F401  (resuelve los mappers antes de tocar modelos)

import pytest

from itcj2.apps.helpdesk.pages.origins import (
    _ORIGIN_ALIASES,
    _ORIGIN_DEFS,
    HD_PAGE_TO_ORIGIN,
    build_origins,
    origin_for_page,
    origin_qs,
    resolve_origin,
)
from itcj2.apps.helpdesk.pages.nav import HD_PAGE_MODULES
from itcj2.templates import ENDPOINT_MAP


def test_todo_slug_resuelve_a_una_url_real():
    """Ningún slug puede quedarse sin URL: eso es el bug que originó el registro."""
    origins = build_origins()
    assert set(origins) == set(_ORIGIN_DEFS), (
        "algún endpoint de _ORIGIN_DEFS no existe en ENDPOINT_MAP"
    )
    for slug, entry in origins.items():
        assert entry["url"].startswith("/help-desk/"), f"{slug} -> {entry['url']}"
        assert "{" not in entry["url"], f"{slug} tiene placeholders sin resolver"
        assert entry["label"]
        assert entry["icon"]


def test_las_urls_vienen_de_endpoint_map():
    for slug, (endpoint, _label, _icon) in _ORIGIN_DEFS.items():
        assert endpoint in ENDPOINT_MAP, f"{slug}: endpoint fantasma {endpoint}"
        assert build_origins()[slug]["url"] == ENDPOINT_MAP[endpoint]


@pytest.mark.parametrize(
    "alias,destino",
    [("secretary_dashboard", "secretary"), ("admin", "admin_tickets_list"), ("dashboard", "my_tickets")],
)
def test_los_alias_historicos_resuelven(alias, destino):
    """Las notificaciones ya enviadas llevan slugs viejos; deben seguir sirviendo."""
    assert resolve_origin(alias) == resolve_origin(destino)


def test_slug_desconocido_o_vacio_devuelve_none():
    assert resolve_origin("no-existe") is None
    assert resolve_origin("") is None
    assert resolve_origin(None) is None


def test_todo_hd_page_tiene_origen():
    """Un origen sin mapear reproduce el 'no mapea bien de dónde vienes'."""
    faltantes = set(HD_PAGE_MODULES) - set(HD_PAGE_TO_ORIGIN)
    assert not faltantes, f"hd_page sin slug de origen: {sorted(faltantes)}"


def test_los_origenes_mapeados_existen():
    invalidos = {
        page: slug
        for page, slug in HD_PAGE_TO_ORIGIN.items()
        if resolve_origin(slug) is None
    }
    assert not invalidos, f"hd_page apuntando a slugs inexistentes: {invalidos}"


def test_origin_for_page():
    assert origin_for_page("technician_dashboard") == "technician"
    assert origin_for_page("admin_stats") == "stats"
    assert origin_for_page("inventory_reports_verification") == "inventory_verification"
    assert origin_for_page(None) is None
    assert origin_for_page("pagina_inventada") is None


def test_origin_qs_normaliza_alias_y_calla_lo_invalido():
    assert origin_qs("technician") == "?from=technician"
    assert origin_qs("secretary_dashboard") == "?from=secretary"
    assert origin_qs("admin", prefix="&") == "&from=admin_tickets_list"
    assert origin_qs("no-existe") == ""
    assert origin_qs(None) == ""


def test_secretary_ya_no_apunta_a_la_vista_de_admin():
    """Cambio de destino deliberado: el slug decía 'secretaría' y llevaba a admin."""
    assert resolve_origin("secretary")["url"] == "/help-desk/secretary/"


@pytest.mark.parametrize(
    "slug,url",
    [
        ("my_tickets", "/help-desk/user/my-tickets"),
        ("technician", "/help-desk/technician/dashboard"),
        ("department", "/help-desk/department/"),
        ("stats", "/help-desk/admin/stats"),
        ("analysis", "/help-desk/admin/analysis"),
    ],
)
def test_los_cuatro_destinos_que_estaban_rotos(slug, url):
    """`/user/tickets`, `/user/dashboard`, `/department/tickets` y
    `/secretary/dashboard` eran 404. Estos son los destinos correctos."""
    assert resolve_origin(slug)["url"] == url
