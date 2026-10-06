"""R7 (fix round 1): las guardas de configuracion responden ANTES de leer el cuerpo.

Antes de pasar las rutas al threadpool, un POST bloqueado por el modo de revision
(`_mode_block`, `_alternate_mode_block`, `_recheck_block`) o por el switch de
impresion (`printing_enabled`) respondia su 400/404 sin tocar el cuerpo de la
peticion: daba igual que el formulario viniera roto. Spec §4 invariante 3: las
respuestas visibles no cambian. Estas guardas son lecturas de configuracion pura
(la prueba estructural `test_route_threadpool_convention.py` las deja en el cuerpo
`async`, antes del `await request.form()`).

Prueba: un POST con `Content-Type: multipart/form-data` SIN boundary hace que
`await request.form()` falle con 400 (sin `X-Tt-Error`). Una ruta bloqueada tiene
que contestar su propio rechazo, no ese.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

PERMS = (
    "titulatec.enrollment_access.page.list",
    "titulatec.enrollment_access.api.grant",
    "titulatec.enrollment_access.api.return",
    "titulatec.enrollment_access.api.reject",
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.cancel",
    "titulatec.certificate.page.list",
)
CUERPO_ROTO = {"content": b"no-es-un-formulario", "headers": {"Content-Type": "multipart/form-data"}}

# (ruta, modo del revisor en el que la guarda rechaza, fragmento del motivo o None)
ACCESOS = "/titulatec/admin/accesos"
SOLICITUDES = "/titulatec/admin/solicitudes"
BLOQUEADAS = [
    pytest.param(f"{ACCESOS}/1/devolver", "alterno", None, id="accesos-devolver-en-alterno"),
    pytest.param(f"{ACCESOS}/1/rechazar", "oficial", None, id="accesos-rechazar-en-oficial"),
    pytest.param(f"{ACCESOS}/1/reenviar", "oficial", None, id="accesos-reenviar-en-oficial"),
    pytest.param(f"{SOLICITUDES}/1/aprobar", "alterno", "Centro de Cómputo", id="solicitudes-aprobar-en-alterno"),
    pytest.param(f"{SOLICITUDES}/1/rechazar", "alterno", "Centro de Cómputo", id="solicitudes-rechazar-en-alterno"),
    pytest.param(f"{SOLICITUDES}/1/reenviar", "alterno", "Centro de Cómputo", id="solicitudes-reenviar-en-alterno"),
    pytest.param(f"{SOLICITUDES}/1/reenviar-aviso", "alterno", "Centro de Cómputo",
                 id="solicitudes-reenviar-aviso-en-alterno"),
    pytest.param(f"{SOLICITUDES}/1/revocar", "alterno", "Centro de Cómputo", id="solicitudes-revocar-en-alterno"),
    pytest.param(f"{SOLICITUDES}/1/reconsultar", "oficial", "solo existe en el modo sii",
                 id="solicitudes-reconsultar-fuera-de-sii"),
]


@pytest.mark.parametrize("url,modo,fragmento", BLOQUEADAS)
def test_el_corte_de_modo_responde_antes_de_leer_el_cuerpo(
    client_as, make_head, monkeypatch, url, modo, fragmento,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import EnrollmentRequestService

    reviewer = {"alterno": "computer_center", "oficial": "school_services"}[modo]
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode", staticmethod(lambda: reviewer))
    actor = make_head(perm_codes=PERMS)

    resp = client_as(actor).post(url, **CUERPO_ROTO)

    assert resp.status_code == 400, resp.text[:300]
    motivo = unquote(resp.headers.get("X-Tt-Error", ""))
    assert motivo, "respondio el error de lectura del form, no el rechazo de la guarda"
    if fragmento:
        assert fragmento in motivo, motivo


def test_con_la_impresion_apagada_generar_lote_responde_404_antes_de_leer_el_cuerpo(
    client_as, make_head,
):
    actor = make_head(perm_codes=PERMS)

    resp = client_as(actor).post("/titulatec/admin/constancias/library_clearance/lote", **CUERPO_ROTO)

    assert resp.status_code == 404, resp.text[:300]
