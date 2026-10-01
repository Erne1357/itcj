"""La sesión caducada durante una navegación HTMX no debe volcar el login dentro del shell.

Contexto
--------
``helpdesk`` y ``adhoc`` navegan con ``hx-boost``: el clic en un enlace no es una
navegación del documento sino un XHR que sustituye un trozo del DOM. Cuando la
cookie ``itcj_token`` ha caducado, la página lanza ``PageLoginRequired`` y el
manejador de :mod:`itcj2.main` responde ``302`` a ``/itcj/login``.

Un ``302`` en un XHR **lo sigue el navegador de forma transparente**: HTMX nunca
ve el redirect, recibe un 200 con el HTML del login y lo inyecta donde iba el
contenido. El usuario acaba con un formulario de acceso metido dentro del marco
de la app, sin barra de direcciones que lo explique, y la URL sigue siendo la de
la página que pidió.

El remedio es el que documenta HTMX: para una petición suya (``HX-Request: true``)
hay que contestar ``200`` con la cabecera ``HX-Redirect``, que HTMX traduce a una
navegación real del documento.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from itcj2.exceptions import PageLoginRequired


@pytest.fixture()
def app_con_pagina_protegida() -> FastAPI:
    """App mínima con los manejadores reales de ``itcj2.main`` y una ruta que exige sesión."""
    from itcj2.main import create_app

    app = create_app()

    @app.get("/_prueba/pagina-protegida")
    def _protegida():  # pragma: no cover - el cuerpo nunca se alcanza
        raise PageLoginRequired()

    return app


def test_navegacion_normal_sigue_redirigiendo_con_302(app_con_pagina_protegida: FastAPI):
    """Sin cabecera de HTMX el comportamiento no cambia: 302 a /itcj/login."""
    client = TestClient(app_con_pagina_protegida, follow_redirects=False)

    res = client.get("/_prueba/pagina-protegida")

    assert res.status_code == 302
    assert res.headers["location"] == "/itcj/login"
    assert "HX-Redirect" not in res.headers


def test_peticion_htmx_recibe_hx_redirect_en_vez_de_302(app_con_pagina_protegida: FastAPI):
    """Con ``HX-Request: true`` la respuesta es 200 + ``HX-Redirect``.

    Es la única forma de que HTMX haga una navegación real del documento: un 302
    lo seguiría el propio navegador y el HTML del login acabaría inyectado dentro
    del shell de la app.
    """
    client = TestClient(app_con_pagina_protegida, follow_redirects=False)

    res = client.get("/_prueba/pagina-protegida", headers={"HX-Request": "true"})

    assert res.status_code == 200, "un 3xx lo sigue el XHR de forma transparente"
    assert res.headers.get("HX-Redirect") == "/itcj/login"
    assert res.text == "", "el cuerpo tiene que ir vacío: nada que inyectar"


def test_el_cuerpo_de_la_respuesta_htmx_no_trae_el_formulario_de_login(
    app_con_pagina_protegida: FastAPI,
):
    """Regresión directa del síntoma: ni rastro del formulario en el cuerpo."""
    client = TestClient(app_con_pagina_protegida, follow_redirects=False)

    res = client.get("/_prueba/pagina-protegida", headers={"HX-Request": "true"})

    cuerpo = res.text.lower()
    assert "<form" not in cuerpo
    assert "password" not in cuerpo
