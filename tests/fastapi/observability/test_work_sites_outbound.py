"""Fase 4b (Task 2): salientes — `msgraph_mail.graph_send_mail` (MS Graph,
`requests.post`) y los tres `httpx.get(..., timeout=12.0)` de
`mundial_service` (fixture, standings, diagnóstico). Ambos con
`measured_outbound(target)`.

Plan de rendimiento TitulaTec (R1): dos destinos más, `msal` (la renovación
silenciosa del token de MS Graph, `msgraph_mail.acquire_token_silent`) y `sii`
(la consulta del NIP, `eligibility_service.fetch_sii_nip`).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
import requests

from tests.fastapi.titulatec._sii_fake import sii  # noqa: F401  (fixture)

from ._work_site_helpers import OUTBOUND, counts, delta, only


# ---------------------------------------------------------------------------
# core/utils/msgraph_mail.py — graph_send_mail
# ---------------------------------------------------------------------------

class TestMsgraphMail:
    LABELS = {"target": "msgraph"}

    def test_ok_status_records_ok_and_returns_the_same_response(self, monkeypatch):
        from itcj2.core.utils import msgraph_mail

        fake_response = SimpleNamespace(status_code=202)
        monkeypatch.setattr(
            msgraph_mail.requests, "post", lambda *a, **kw: fake_response
        )

        before = counts(self.LABELS, name=OUTBOUND)
        result = msgraph_mail.graph_send_mail("tok", "Asunto", "<p>hola</p>", ["a@b.com"])

        assert result is fake_response
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    def test_status_gte_400_records_error_and_still_returns_the_response(self, monkeypatch):
        """`graph_send_mail` no lanza en un status de error (no hace
        `raise_for_status`): sigue regresando la respuesta tal cual, solo se
        clasifica como outcome=error."""
        from itcj2.core.utils import msgraph_mail

        fake_response = SimpleNamespace(status_code=503)
        monkeypatch.setattr(
            msgraph_mail.requests, "post", lambda *a, **kw: fake_response
        )

        before = counts(self.LABELS, name=OUTBOUND)
        result = msgraph_mail.graph_send_mail("tok", "Asunto", "<p>hola</p>", ["a@b.com"])

        assert result is fake_response
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("error")

    def test_timeout_records_timeout_and_reraises_the_same_exception(self, monkeypatch):
        from itcj2.core.utils import msgraph_mail

        exc = requests.Timeout("lento")

        def _raise(*a, **kw):
            raise exc

        monkeypatch.setattr(msgraph_mail.requests, "post", _raise)

        before = counts(self.LABELS, name=OUTBOUND)
        with pytest.raises(requests.Timeout) as info:
            msgraph_mail.graph_send_mail("tok", "Asunto", "<p>hola</p>", ["a@b.com"])

        assert info.value is exc
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("timeout")


# ---------------------------------------------------------------------------
# core/services/mundial_service.py — los tres httpx.get(..., timeout=12.0)
# ---------------------------------------------------------------------------

class _FakeHttpxResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=self,
            )

    def json(self):
        return self._json


class TestMundialServiceFootballApi:
    LABELS = {"target": "football_api"}

    def test_fetch_api_all_records_one_ok_observation(self, monkeypatch):
        from itcj2.core.services import mundial_service

        monkeypatch.setattr(
            mundial_service, "_provider_cfg",
            lambda: ("footballdata", "key", "url"),
        )
        monkeypatch.setattr(
            httpx, "get", lambda *a, **kw: _FakeHttpxResponse(200, {"matches": []}),
        )

        before = counts(self.LABELS, name=OUTBOUND)
        result = mundial_service._fetch_api_all()

        assert result is None  # lista vacía -> `out or None`
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    def test_fetch_api_standings_records_one_ok_observation(self, monkeypatch):
        from itcj2.core.services import mundial_service

        monkeypatch.setattr(
            mundial_service, "_provider_cfg",
            lambda: ("footballdata", "key", "url"),
        )
        monkeypatch.setattr(
            httpx, "get", lambda *a, **kw: _FakeHttpxResponse(200, {"standings": []}),
        )

        before = counts(self.LABELS, name=OUTBOUND)
        result = mundial_service._fetch_api_standings()

        assert result is None
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    def test_api_diagnostic_records_one_ok_observation(self, monkeypatch):
        from itcj2.core.services import mundial_service

        monkeypatch.setattr(
            mundial_service, "_provider_cfg",
            lambda: ("footballdata", "key", "url"),
        )
        monkeypatch.setattr(
            httpx, "get", lambda *a, **kw: _FakeHttpxResponse(200, {"matches": []}),
        )

        before = counts(self.LABELS, name=OUTBOUND)
        info = mundial_service.api_diagnostic()

        assert info["ok"] is True
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    def test_fetch_api_all_status_gte_400_records_error(self, monkeypatch):
        """`raise_for_status()` convierte el status en excepción: cae en el
        `except Exception` propio de la función (degrada a None), pero la
        medición debe clasificarlo como error, no como ok."""
        from itcj2.core.services import mundial_service

        monkeypatch.setattr(
            mundial_service, "_provider_cfg",
            lambda: ("footballdata", "key", "url"),
        )
        monkeypatch.setattr(
            httpx, "get", lambda *a, **kw: _FakeHttpxResponse(503),
        )

        before = counts(self.LABELS, name=OUTBOUND)
        result = mundial_service._fetch_api_all()

        assert result is None
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("error")

    def test_fetch_api_all_timeout_records_timeout(self, monkeypatch):
        from itcj2.core.services import mundial_service

        def _raise(*a, **kw):
            raise httpx.ReadTimeout("lento")

        monkeypatch.setattr(
            mundial_service, "_provider_cfg",
            lambda: ("footballdata", "key", "url"),
        )
        monkeypatch.setattr(httpx, "get", _raise)

        before = counts(self.LABELS, name=OUTBOUND)
        result = mundial_service._fetch_api_all()

        assert result is None  # degrada, no propaga (comportamiento previo)
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("timeout")


# ---------------------------------------------------------------------------
# core/utils/msgraph_mail.py — acquire_token_silent (target `msal`)
# ---------------------------------------------------------------------------

class _FakeMsalApp:
    """Lo mínimo de `ConfidentialClientApplication` que usa `acquire_token_silent`."""

    def __init__(self, result=None, exc=None, accounts=None):
        self.result = result
        self.exc = exc
        self.accounts = [{"home_account_id": "home-1"}] if accounts is None else accounts
        self.silent_calls = []

    def get_accounts(self):
        return self.accounts

    def acquire_token_silent(self, scopes, account=None):
        self.silent_calls.append((scopes, account))
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture()
def msal_silencioso(monkeypatch):
    """Arma `acquire_token_silent("titulatec")` sin disco ni red.

    Devuelve `armar(...)`, que instala la app falsa y regresa `(app, cache,
    guardados)`: `guardados` anota cada `save_cache(app_key, cache)` para
    probar que la caché de tokens se sigue cargando y guardando igual.
    """
    from itcj2.core.utils import msgraph_mail

    def armar(result=None, exc=None, account_info="__default__", accounts=None):
        app = _FakeMsalApp(result=result, exc=exc, accounts=accounts)
        cache = SimpleNamespace(has_state_changed=False)
        guardados = []
        if account_info == "__default__":
            account_info = {"home_account_id": "home-1"}
        monkeypatch.setattr(msgraph_mail, "load_cache", lambda app_key: cache)
        monkeypatch.setattr(msgraph_mail, "get_msal_app", lambda app_key, c=None: app)
        monkeypatch.setattr(msgraph_mail, "read_account_info", lambda app_key: account_info)
        monkeypatch.setattr(
            msgraph_mail, "save_cache", lambda app_key, c: guardados.append((app_key, c))
        )
        return app, cache, guardados

    return armar


class TestMsalAcquireTokenSilent:
    LABELS = {"target": "msal"}
    SIN_OBSERVACIONES = {"ok": 0.0, "error": 0.0, "timeout": 0.0}

    def test_token_obtenido_registra_ok_y_devuelve_el_token(self, msal_silencioso):
        from itcj2.core.utils import msgraph_mail

        app, cache, guardados = msal_silencioso(result={"access_token": "tok-1"})

        before = counts(self.LABELS, name=OUTBOUND)
        token = msgraph_mail.acquire_token_silent("titulatec")

        assert token == "tok-1"
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")
        # La caché de tokens se sigue guardando igual.
        assert guardados == [("titulatec", cache)]
        assert app.silent_calls == [(msgraph_mail._SCOPES_FULL, {"home_account_id": "home-1"})]

    @pytest.mark.parametrize(
        "result",
        [
            pytest.param({"error": "invalid_grant", "error_description": "caducó"}, id="error-de-aad"),
            pytest.param(None, id="sin-token-en-cache"),
            pytest.param({}, id="respuesta-vacia"),
        ],
    )
    def test_sin_access_token_registra_error_y_devuelve_none(self, msal_silencioso, result):
        from itcj2.core.utils import msgraph_mail

        _app, cache, guardados = msal_silencioso(result=result)

        before = counts(self.LABELS, name=OUTBOUND)
        token = msgraph_mail.acquire_token_silent("titulatec")

        assert token is None
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("error")
        assert guardados == [("titulatec", cache)]

    def test_timeout_registra_timeout_y_relanza_la_misma_excepcion(self, msal_silencioso):
        from itcj2.core.utils import msgraph_mail

        exc = requests.Timeout("lento")
        msal_silencioso(exc=exc)

        before = counts(self.LABELS, name=OUTBOUND)
        with pytest.raises(requests.Timeout) as info:
            msgraph_mail.acquire_token_silent("titulatec")

        assert info.value is exc
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("timeout")

    def test_otra_excepcion_registra_error_y_relanza_la_misma(self, msal_silencioso):
        from itcj2.core.utils import msgraph_mail

        exc = requests.ConnectionError("sin red")
        msal_silencioso(exc=exc)

        before = counts(self.LABELS, name=OUTBOUND)
        with pytest.raises(requests.ConnectionError) as info:
            msgraph_mail.acquire_token_silent("titulatec")

        assert info.value is exc
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("error")

    @pytest.mark.parametrize(
        "armado",
        [
            pytest.param({"account_info": None}, id="sin-cuenta-conectada"),
            pytest.param({"accounts": []}, id="cuenta-ausente-de-la-cache"),
            pytest.param(
                {"accounts": [{"home_account_id": "otra"}]}, id="cuenta-distinta"
            ),
        ],
    )
    def test_sin_cuenta_no_hay_llamada_ni_observacion(self, msal_silencioso, armado):
        """Sin cuenta (o sin su entrada en la caché) MSAL ni se llama: contarlo
        como una llamada `ok` de 0 s taparía el p50 de las llamadas reales."""
        from itcj2.core.utils import msgraph_mail

        app, _cache, _guardados = msal_silencioso(result={"access_token": "x"}, **armado)

        before = counts(self.LABELS, name=OUTBOUND)
        token = msgraph_mail.acquire_token_silent("titulatec")

        assert token is None
        assert app.silent_calls == []
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == self.SIN_OBSERVACIONES

    def test_app_key_invalido_no_registra_nada(self, msal_silencioso):
        from itcj2.core.utils import msgraph_mail

        msal_silencioso(result={"access_token": "x"})

        before = counts(self.LABELS, name=OUTBOUND)
        assert msgraph_mail.acquire_token_silent("../etc") is None
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == self.SIN_OBSERVACIONES


# ---------------------------------------------------------------------------
# titulatec/services/eligibility_service.py — fetch_sii_nip (target `sii`)
# ---------------------------------------------------------------------------

class TestSiiNip:
    """`fetch_sii_nip` no lanza nunca: devuelve `(Secret | None, falla)`. La
    medición va DENTRO de su `try`, así que una excepción de la consulta se
    clasifica y luego la convierte en `falla` el `except` de siempre."""

    LABELS = {"target": "sii"}
    SIN_OBSERVACIONES = {"ok": 0.0, "error": 0.0, "timeout": 0.0}

    def test_nip_entregado_registra_ok_y_conserva_el_retorno(self, sii):
        from itcj2.apps.titulatec.services import eligibility_service as elig

        sii.alumno("99580201", nip="4321")

        before = counts(self.LABELS, name=OUTBOUND)
        secret, falla = elig.fetch_sii_nip("99580201")

        assert falla is None
        assert secret is not None and secret.reveal() == "4321"
        assert repr(secret) == "****"
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    def test_sii_sin_nip_es_una_respuesta_ok(self, sii):
        """El SII respondió (0 filas): no hay NIP, pero la llamada salió bien."""
        from itcj2.apps.titulatec.services import eligibility_service as elig

        sii.alumno("99580202")
        sii.sin_nip("99580202")

        before = counts(self.LABELS, name=OUTBOUND)
        assert elig.fetch_sii_nip("99580202") == (None, None)
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("ok")

    @pytest.mark.parametrize(
        "preparar, falla",
        [
            pytest.param("nip_caido", "SiiUnavailable", id="sii-caido"),
            pytest.param("nip_invalido", "SiiQueryError", id="consulta-invalida"),
        ],
    )
    def test_falla_del_sii_registra_error_y_devuelve_la_falla(self, sii, preparar, falla):
        from itcj2.apps.titulatec.services import eligibility_service as elig

        sii.alumno("99580203")
        getattr(sii, preparar)("99580203")

        before = counts(self.LABELS, name=OUTBOUND)
        assert elig.fetch_sii_nip("99580203") == (None, falla)
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("error")

    def test_timeout_registra_timeout_y_sigue_sin_lanzar(self, sii, monkeypatch):
        from itcj2.apps.titulatec.services import eligibility_service as elig
        from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

        sii.alumno("99580204")

        def _lento(*a, **kw):
            raise TimeoutError("lento")

        monkeypatch.setattr(FakeSiiClient, "query", _lento)

        before = counts(self.LABELS, name=OUTBOUND)
        assert elig.fetch_sii_nip("99580204") == (None, "TimeoutError")
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == only("timeout")

    def test_con_el_sii_deshabilitado_no_hay_llamada_ni_observacion(self, sii):
        """`disabled` (el caso de producción hoy) lanza `SiiUnavailable` al pedir
        el cliente, ANTES de cualquier petición: no es una llamada saliente, y
        contarla como `error` convertiría el panel en una alarma permanente."""
        from itcj2.apps.titulatec.services import eligibility_service as elig

        sii.alumno("99580205")
        sii.backend = "disabled"

        before = counts(self.LABELS, name=OUTBOUND)
        assert elig.fetch_sii_nip("99580205") == (None, elig.NIP_UNAVAILABLE)
        assert delta(before, counts(self.LABELS, name=OUTBOUND)) == self.SIN_OBSERVACIONES
