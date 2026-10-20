"""`acquire_token_silent` sin cuenta conectada: ni MSAL ni la caché de tokens.

Perf 2026-10-07: en prod la cuenta de correo de maint no está conectada y aun
así asignar/resolver tardaban 200-400 ms: se construía la app de MSAL
(descubrimiento del tenant) y se leía la caché de tokens de disco ANTES de ver
que no había cuenta (medido en dev: 320 de 335 ms de una asignación). Va en
core porque lo pagaba cualquier app que manda correo sin cuenta conectada.
"""
from unittest.mock import patch

from itcj2.core.utils import msgraph_mail


def _prohibido(*a, **k):
    raise AssertionError("sin cuenta conectada no se toca MSAL ni la caché de tokens")


def test_sin_cuenta_no_construye_msal_ni_lee_la_cache():
    with patch.object(msgraph_mail, "read_account_info", return_value=None), \
         patch.object(msgraph_mail, "get_msal_app", side_effect=_prohibido), \
         patch.object(msgraph_mail, "load_cache", side_effect=_prohibido):
        assert msgraph_mail.acquire_token_silent("maint") is None


def test_app_key_invalida_sigue_siendo_none_sin_msal():
    with patch.object(msgraph_mail, "get_msal_app", side_effect=_prohibido), \
         patch.object(msgraph_mail, "load_cache", side_effect=_prohibido):
        assert msgraph_mail.acquire_token_silent("../no-valida") is None
