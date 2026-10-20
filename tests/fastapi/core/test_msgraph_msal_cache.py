"""MSAL sin re-descubrimiento por correo (plan de rendimiento TitulaTec, R1, H2).

`get_msal_app` construía un `ConfidentialClientApplication` por llamada, cada
uno con su propio `http_cache` vacío: cada correo pagaba el descubrimiento del
tenant (`/.well-known/openid-configuration`, 180-220 ms medidos en producción).
La solución es un `http_cache` de MÓDULO compartido por todas las apps de un
proceso.

Lo que NO debe cambiar (spec §3.2): se sigue creando una app por llamada y cada
una carga SU caché de tokens del archivo (`load_cache(app_key)`). Compartir la
app compartiría también su `token_cache` entre `app_key`s distintas.

La red se simula en `requests.Session.send`, la capa más baja que msal usa
siempre (su `http_client` es una `Session`); así la prueba cuenta peticiones
reales sin depender de cómo msal las envuelva en cada versión.
"""
import json
from types import SimpleNamespace

import msal
import pytest
import requests

from itcj2.core.utils import msgraph_mail as mg

_TENANT = "https://login.microsoftonline.com/tenant-de-prueba"
_OPENID_CONFIG = {
    "issuer": f"{_TENANT}/v2.0",
    "authorization_endpoint": f"{_TENANT}/oauth2/v2.0/authorize",
    "token_endpoint": f"{_TENANT}/oauth2/v2.0/token",
    "device_authorization_endpoint": f"{_TENANT}/oauth2/v2.0/devicecode",
}


@pytest.fixture()
def red(monkeypatch, tmp_path):
    """Credenciales de mentira, caché HTTP del módulo vacía y la red simulada.

    Devuelve la lista de URLs pedidas. Cada prueba arranca con el `http_cache`
    del módulo vacío (es de proceso: si no, el orden de las pruebas decidiría
    cuántas peticiones se ven) y la carpeta de tokens en `tmp_path` (leer la
    caché de un `app_key` real tocaría `instance/apps/`).
    """
    monkeypatch.setattr(mg, "AUTHORITY", _TENANT)
    monkeypatch.setattr(mg, "CLIENT_ID", "client-de-prueba")
    monkeypatch.setattr(mg, "CLIENT_SECRET", "secreto-de-prueba")
    monkeypatch.setattr(mg, "_INSTANCE_BASE", tmp_path)
    monkeypatch.setattr(mg, "_MSAL_HTTP_CACHE", {}, raising=False)

    urls: list[str] = []

    def _send(self, request, **kwargs):
        urls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(_OPENID_CONFIG).encode("utf-8")
        response.headers["Content-Type"] = "application/json"
        response.encoding = "utf-8"
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.Session, "send", _send)
    return urls


def test_dos_apps_seguidas_hacen_una_sola_peticion_de_descubrimiento(red):
    mg.get_msal_app("titulatec")
    mg.get_msal_app("titulatec")

    assert len(red) == 1, f"se esperaba 1 descubrimiento, hubo {len(red)}: {red}"
    assert red[0].endswith("/.well-known/openid-configuration")


def test_apps_de_distinto_app_key_comparten_el_descubrimiento(red):
    """Un solo registro de Azure AD para todas las apps (docstring del módulo):
    el descubrimiento es del tenant, no del `app_key`."""
    for app_key in ("titulatec", "maint", "agendatec", "helpdesk"):
        mg.get_msal_app(app_key)

    assert len(red) == 1


def test_sin_cache_compartida_cada_app_volveria_a_descubrir(red, monkeypatch):
    """Control negativo: la prueba de arriba falla de verdad si la caché no se
    comparte. Con un `http_cache` NUEVO por llamada (el comportamiento de antes)
    salen dos peticiones."""
    original = msal.ConfidentialClientApplication

    def _app_con_cache_propia(*args, **kwargs):
        kwargs["http_cache"] = {}
        return original(*args, **kwargs)

    monkeypatch.setattr(mg.msal, "ConfidentialClientApplication", _app_con_cache_propia)

    mg.get_msal_app("titulatec")
    mg.get_msal_app("titulatec")

    assert len(red) == 2


def test_cada_llamada_crea_su_app_y_carga_su_cache_de_tokens(red):
    """La semántica de la caché de tokens NO cambia: una app nueva por llamada,
    cada una con la caché que `load_cache(app_key)` leyó de su archivo."""
    primera = mg.get_msal_app("titulatec")
    segunda = mg.get_msal_app("titulatec")

    assert primera is not segunda
    assert primera.token_cache is not segunda.token_cache


def test_la_cache_de_tokens_explicita_se_respeta(red):
    cache = msal.SerializableTokenCache()

    app = mg.get_msal_app("titulatec", cache)

    assert app.token_cache is cache


def test_la_app_recibe_el_http_cache_del_modulo(monkeypatch):
    """El contrato del plan: `_MSAL_HTTP_CACHE` (un dict de módulo) viaja como
    `http_cache=` en CADA `ConfidentialClientApplication`."""
    assert isinstance(mg._MSAL_HTTP_CACHE, dict)
    capturado = []

    def _falsa(*args, **kwargs):
        capturado.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(mg.msal, "ConfidentialClientApplication", _falsa)
    cache = msal.SerializableTokenCache()

    mg.get_msal_app("titulatec", cache)
    mg.get_msal_app("maint", cache)

    assert len(capturado) == 2
    for kwargs in capturado:
        assert kwargs["http_cache"] is mg._MSAL_HTTP_CACHE
        assert kwargs["token_cache"] is cache
        assert kwargs["authority"] == mg.AUTHORITY
        assert kwargs["client_credential"] == mg.CLIENT_SECRET


def test_la_cache_http_del_modulo_no_guarda_tokens(red):
    """msal documenta que su `http_cache` solo trae contenido barato de obtener
    (descubrimiento y llaves de throttling hasheadas): nada de tokens ni PII.
    Se verifica sobre lo que de verdad queda guardado tras construir la app."""
    mg.get_msal_app("titulatec")

    guardado = repr(mg._MSAL_HTTP_CACHE)
    assert "secreto-de-prueba" not in guardado
    assert "access_token" not in guardado
    assert "refresh_token" not in guardado
