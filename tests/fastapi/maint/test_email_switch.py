"""Interruptor de correo de maint (`MAINT_EMAIL_ENABLED`).

2026-10-07: maint no tiene cuenta de correo conectada A PROPÓSITO, pero cada
asignación, resolución y cancelación intentaba mandar el aviso y dejaba un
«Maint email account not connected» en el log. El correo queda APAGADO por
omisión; el código no se borra: con `MAINT_EMAIL_ENABLED=true` en el `.env` (y la
cuenta conectada) vuelve a salir igual que antes.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from itcj2.apps.maint.services.email_helper import MaintEmailHelper
from itcj2.config import Settings, get_settings

_USUARIO = SimpleNamespace(id=2, email="alguien@example.invalid", full_name="Alguien")
_TICKET = SimpleNamespace(id=1, ticket_number="MANT-2026-000001", requester=_USUARIO,
                          title="t", description="d")

_ENVIOS = [
    ("send_assigned", (_TICKET, _USUARIO)),
    ("send_resolved", (_TICKET,)),
    ("send_overdue", (_TICKET, _USUARIO)),
    ("send_canceled", (_TICKET, _USUARIO)),
]


def test_por_omision_esta_apagado(monkeypatch):
    monkeypatch.delenv("MAINT_EMAIL_ENABLED", raising=False)
    assert Settings(_env_file=None).MAINT_EMAIL_ENABLED is False


@pytest.mark.parametrize("metodo, args", _ENVIOS, ids=[m for m, _ in _ENVIOS])
def test_apagado_no_busca_token_ni_manda(monkeypatch, metodo, args):
    monkeypatch.setattr(get_settings(), "MAINT_EMAIL_ENABLED", False)

    def _prohibido(*a, **k):
        raise AssertionError("con el correo de maint apagado no se toca Graph")

    with patch("itcj2.apps.maint.services.email_helper._acquire_token", side_effect=_prohibido), \
         patch("itcj2.apps.maint.services.email_helper._send", side_effect=_prohibido):
        assert getattr(MaintEmailHelper, metodo)(None, *args) is False


@pytest.mark.parametrize("metodo, args", _ENVIOS, ids=[m for m, _ in _ENVIOS])
def test_encendido_sigue_el_camino_de_siempre(monkeypatch, metodo, args):
    monkeypatch.setattr(get_settings(), "MAINT_EMAIL_ENABLED", True)

    with patch("itcj2.apps.maint.services.email_helper._acquire_token",
               return_value=None) as token:
        assert getattr(MaintEmailHelper, metodo)(None, *args) is False
    token.assert_called_once()
