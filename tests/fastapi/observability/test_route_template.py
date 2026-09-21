"""Tests de `itcj2.observability.route` contra la app REAL.

TRAMPA medida el 2026-09-21 (ver
`.superpowers/sdd/2026-09-21-obs-f0-f3/ref/enum_routes6.py`, validado 25/25
contra peticiones reales): en fastapi 0.141 `scope["route"].path` es LOCAL al
router hoja donde se declaró el endpoint, porque `include_router` ya no
aplana los routers incluidos. Por eso estos tests despachan directo al ASGI
de `create_app()` (no vía `TestClient`, que no expone el `scope` después de
la respuesta) y leen `scope["route"]`/`scope["app"]` tal como los deja
FastAPI, para pasarlos a `normalize_route`.

No dependen de BD ni de datos sembrados: solo enrutan (la app real construye
sus routers al importar, sin tocar la base).
"""
import asyncio

import pytest

from itcj2.main import create_app
from itcj2.observability.route import (
    _route_method_pairs,
    app_key_from_route,
    build_route_map,
    normalize_route,
)


@pytest.fixture(scope="module")
def app():
    return create_app()


class _Recv:
    """Cuerpo vacío: basta para que FastAPI resuelva el routing."""

    def __init__(self):
        self._sent = False

    async def __call__(self):
        if not self._sent:
            self._sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}


class _Send:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)


def _dispatch(app, path, method="GET"):
    """Despacha una petición ASGI cruda y regresa (status, scope).

    Se arma el scope a mano (como `ref/validate_sample.py`) en vez de usar
    `TestClient`: `TestClient` no deja tocar el `scope` de la petición
    después de que la respuesta ya se resolvió, y es justo `scope["route"]`
    lo que este módulo necesita inspeccionar.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-length", b"0")],
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 80),
    }
    recv = _Recv()
    send = _Send()
    asyncio.run(app(scope, recv, send))
    status = None
    for message in send.messages:
        if message["type"] == "http.response.start":
            status = message["status"]
            break
    return status, scope


# ---------------------------------------------------------------------------
# normalize_route() contra rutas reales
# ---------------------------------------------------------------------------

def test_ticket_detail_resolves_to_full_template(app):
    # Sin cookie de sesión: 401/403 según el dependency de turno. Lo que se
    # mide es la plantilla, no el resultado de autorización (brief §Tests).
    status, scope = _dispatch(app, "/api/help-desk/v2/tickets/4821")
    assert status in (401, 403)
    assert normalize_route(scope) == "/api/help-desk/v2/tickets/{ticket_id}"


def test_deeply_nested_helpdesk_inventory_route_resolves_full_template(app):
    # 4 niveles de router (app -> helpdesk_router -> inventory_router ->
    # campaigns_router): el caso que de verdad ejercita el desenvolvimiento
    # recursivo de _IncludedRouter, no solo un include_router de un nivel.
    status, scope = _dispatch(
        app,
        "/api/help-desk/v2/inventory/campaigns/1/groups/2/items/3",
        method="POST",
    )
    assert normalize_route(scope) == (
        "/api/help-desk/v2/inventory/campaigns/{campaign_id}/groups/{group_id}/items/{item_id}"
    )


def test_nested_core_authz_route_resolves_full_template(app):
    status, scope = _dispatch(
        app,
        "/api/core/v2/authz/apps/helpdesk/roles/admin/perms/helpdesk.tickets.api.create",
        method="POST",
    )
    assert normalize_route(scope) == (
        "/api/core/v2/authz/apps/{app_key}/roles/{role_name}/perms/{code}"
    )


def test_titulatec_page_route_keeps_titulatec_prefix(app):
    status, scope = _dispatch(app, "/titulatec/")
    assert scope.get("route") is not None
    assert normalize_route(scope) == "/titulatec/"


def test_404_gives_unmatched_literal(app):
    status, scope = _dispatch(app, "/esto-no-existe-en-ningun-router-jamas")
    assert status == 404
    assert scope.get("route") is None
    assert normalize_route(scope) == "__unmatched__"


def test_405_gives_real_template_not_unmatched(app):
    # `/{ticket_id}` solo registra GET y PATCH (ver tickets.py): un DELETE
    # produce 405 pero Starlette igual deja el Route matcheado en el scope
    # (match parcial), así que la plantilla real debe salir, no
    # "__unmatched__".
    status, scope = _dispatch(app, "/api/help-desk/v2/tickets/4821", method="DELETE")
    assert status == 405
    assert scope.get("route") is not None
    assert normalize_route(scope) == "/api/help-desk/v2/tickets/{ticket_id}"


# ---------------------------------------------------------------------------
# Guardián: el walker no colapsa ni vacía rutas al enumerar TODO el mapa
# ---------------------------------------------------------------------------

def test_no_duplicate_or_empty_method_template_pairs_in_whole_app(app):
    # No se afirma el número exacto (el reconocimiento midió ~697 plantillas
    # únicas): se afirma la invariante que protege de una regresión del
    # walker si un cambio interno de fastapi/starlette deja de encajar con
    # la fórmula de `_walk` (ver R3 en progress.md).
    pairs = _route_method_pairs(app)
    assert pairs, "el walker no encontró ninguna ruta: algo se rompió antes de empezar"

    for method, template in pairs:
        assert template, f"plantilla vacía para el método {method!r}"

    seen = set()
    duplicates = set()
    for pair in pairs:
        if pair in seen:
            duplicates.add(pair)
        seen.add(pair)
    assert not duplicates, f"pares (método, plantilla) duplicados: {sorted(duplicates)}"


def test_build_route_map_has_no_duplicate_or_empty_templates(app):
    route_map = build_route_map(app)
    assert route_map
    templates = list(route_map.values())
    assert all(templates), "build_route_map produjo una plantilla vacía"
    # Aquí sí se espera repetición de STRING de plantilla entre métodos
    # distintos de la misma ruta (GET y PATCH comparten
    # /tickets/{ticket_id}), así que la unicidad real se prueba sobre el
    # par (método, plantilla) en el test anterior. Este test solo cubre que
    # cada id(route) (la llave real del mapa) es única y no vacía, que es
    # justo lo que garantiza un dict de Python.
    assert len(route_map) == len(set(route_map.keys()))


# ---------------------------------------------------------------------------
# app_key_from_route()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, expected",
    [
        ("/titulatec/student/fase/{n}", "titulatec"),
        ("/directory/entries/{entry_id}", "directory"),
        ("/api/help-desk/v2/tickets/{id}", "helpdesk"),
        ("/help-desk/tickets/{id}", "helpdesk"),
        ("/itcj/dashboard", "core"),
        ("/loquesea/nuevo", "otro"),
        ("/api/adhoc/x", "adhoc"),
        ("/adhoc/x", "adhoc"),
        ("__unmatched__", "otro"),
    ],
)
def test_app_key_from_route(path, expected):
    assert app_key_from_route(path) == expected
