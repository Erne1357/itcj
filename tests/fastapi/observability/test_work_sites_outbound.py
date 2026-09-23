"""Fase 4b (Task 2): salientes — `msgraph_mail.graph_send_mail` (MS Graph,
`requests.post`) y los tres `httpx.get(..., timeout=12.0)` de
`mundial_service` (fixture, standings, diagnóstico). Ambos con
`measured_outbound(target)`.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
import requests

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
