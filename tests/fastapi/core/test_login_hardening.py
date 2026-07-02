"""Phase 8: rate limit de login + timing-safe."""
from unittest.mock import patch

from itcj2.core.utils import rate_limit
from itcj2.core.services.auth_service import authenticate


def test_rate_limit_util_blocks_after_account_max():
    ip, acct = "10.0.0.9", "rl_acct_x"
    from itcj2.config import get_settings
    max_acct = get_settings().LOGIN_FAIL_MAX_ACCOUNT
    for _ in range(max_acct):
        assert rate_limit.check_login_allowed(ip, acct) is True
        rate_limit.note_login_failure(ip, acct)
    # Al alcanzar el máximo de fallos por cuenta → bloqueado.
    assert rate_limit.check_login_allowed(ip, acct) is False
    # Reset lo libera.
    rate_limit.reset_login_failures(ip, acct)
    assert rate_limit.check_login_allowed(ip, acct) is True


def test_login_endpoint_429_after_repeated_failures(app_client):
    from itcj2.config import get_settings
    max_acct = get_settings().LOGIN_FAIL_MAX_ACCOUNT
    payload = {"control_number": "rl_bad_user", "nip": "nope"}  # non-digit → username path
    with patch("itcj2.core.services.auth_service.authenticate_by_username", return_value=None):
        codes = []
        for _ in range(max_acct + 2):
            r = app_client.post("/api/core/v2/auth/login", json=payload)
            codes.append(r.status_code)
    assert codes[0] == 401
    assert 429 in codes            # en algún punto empieza a bloquear
    assert codes[-1] == 429        # sigue bloqueado


def test_authenticate_missing_user_returns_none(db_session):
    # Path "usuario inexistente": corre el hash señuelo y retorna None sin error.
    assert authenticate(db_session, "00000000", "whatever") is None
