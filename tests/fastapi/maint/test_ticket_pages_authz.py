"""Páginas de tickets de maint: permisos del caché de authz y sin fugas de sesión.

Perf 2026-10-07 (rutas lentas): el detalle y el formulario de alta pedían los
permisos con `get_user_permissions_for_app` (sin caché, ~10 consultas) y el
detalle abría su sesión con `next(get_db())`, que nunca se cerraba. Además eran
`async def` con BD síncrona: bloqueaban el event loop mientras consultaban.
"""
import inspect
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


def _cookie(user_id=10):
    s = get_settings()
    now = int(time.time())
    tok = jwt.encode({"sub": str(user_id), "role": None, "cn": None, "name": "T",
                      "iat": now, "exp": now + 3600}, s.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={tok}"}


@pytest.fixture
def ctx_capturado():
    """Corre la ruta con `render_maint` parcheado y un espía sobre
    `SessionLocal` que entrega sesiones REALES; devuelve `(cliente, contextos,
    sesiones)`. Al terminar la petición ninguna sesión debe quedar con una
    transacción abierta: eso es una conexión retenida. (Contar `close()` no
    basta: el `next(get_db())` viejo cierra al recolectar el generador y luego
    REUSA la sesión, que vuelve a abrir transacción y ya nadie la cierra.)"""
    from itcj2 import database

    real = database.SessionLocal
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    contextos, sesiones = [], []

    def _render(request, template, context=None, status_code=200):
        contextos.append(context or {})
        return HTMLResponse("<ok/>", status_code=status_code)

    def _session(*a, **k):
        s = real(*a, **k)
        sesiones.append(s)
        return s

    with (
        patch("itcj2.apps.maint.pages.tickets.render_maint", side_effect=_render),
        patch.object(database, "SessionLocal", side_effect=_session),
        patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True),
    ):
        with TestClient(app, follow_redirects=False) as c:
            yield c, contextos, sesiones
    for ses in sesiones:
        ses.close()
    app.dependency_overrides.clear()


def _abiertas(sesiones):
    return [s for s in sesiones if s.in_transaction()]


def _perms(*codes):
    return patch("itcj2.core.services.authz_cache.cached_perms", return_value=set(codes))


@pytest.mark.parametrize("perms, esperado", [
    (("maint.tickets.page.detail", "maint.assignments.api.assign"), True),
    (("maint.tickets.page.detail",), False),
])
def test_el_detalle_toma_can_assign_del_cache_y_cierra_su_sesion(ctx_capturado, perms, esperado):
    c, contextos, sesiones = ctx_capturado
    with _perms(*perms):
        r = c.get("/maint/tickets/5", headers=_cookie())

    assert r.status_code == 200
    assert contextos[-1]["can_assign"] is esperado
    assert _abiertas(sesiones) == [], "ninguna sesión queda con transacción abierta"


@pytest.mark.parametrize("perms, esperado", [
    (("maint.tickets.page.create", "maint.tickets.api.create.behalf"), True),
    (("maint.tickets.page.create",), False),
])
def test_el_alta_toma_behalf_del_cache_y_cierra_su_sesion(ctx_capturado, perms, esperado):
    c, contextos, sesiones = ctx_capturado
    with _perms(*perms), \
         patch("itcj2.apps.maint.utils.catalog_cache.get_priorities", return_value=[]):
        r = c.get("/maint/tickets/create", headers=_cookie())

    assert r.status_code == 200
    assert contextos[-1]["can_create_behalf"] is esperado
    assert _abiertas(sesiones) == []


@pytest.mark.parametrize("nombre", ["ticket_detail", "ticket_create"])
def test_las_paginas_con_bd_sincrona_no_corren_en_el_event_loop(nombre):
    from itcj2.apps.maint.pages import tickets

    assert not inspect.iscoroutinefunction(getattr(tickets, nombre)), (
        f"{nombre} hace BD síncrona: debe ser `def` (threadpool), no `async def`")
