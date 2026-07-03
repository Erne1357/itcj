"""Security bundle F1a (C6): state=nonce anti-CSRF en el flujo OAuth de correo.

login    → genera nonce aleatorio, lo guarda en Redis (oauth:state:{nonce} ->
           app_key, TTL EMAIL_OAUTH_STATE_TTL) y lo manda como state.
callback → exige sesión admin y un state válido (un solo uso); resuelve app_key
           desde Redis y lo pasa a process_auth_code.

Redis: se usa el Redis REAL del stack (tests corren in-container; fakeredis NO
está en requirements por decisión del spec §4).
"""
import time
from unittest.mock import MagicMock, patch

from itcj2.config import get_settings
from itcj2.core.utils.redis_conn import get_redis
from itcj2.database import get_db

LOGIN_URL = "/itcj/config/email/auth/login?app=helpdesk"
CALLBACK_URL = "/itcj/config/email/auth/callback"


def _override_db(app_client):
    # query(App).filter_by(...).first() → truthy por defecto (app "existe")
    mock_db = MagicMock()

    def override():
        yield mock_db

    app_client.app.dependency_overrides[get_db] = override


def test_setting_default():
    assert get_settings().EMAIL_OAUTH_STATE_TTL == 600


def test_login_stores_nonce_in_redis_and_sends_it_as_state(app_client, auth_headers):
    _override_db(app_client)
    r = get_redis()
    try:
        with patch("itcj2.core.services.authz_cache.cached_roles",
                   return_value={"admin"}), \
             patch("itcj2.core.utils.msgraph_mail.build_auth_url",
                   return_value="https://login.microsoftonline.example/authorize") as mock_build:
            resp = app_client.get(LOGIN_URL, headers=auth_headers,
                                  follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == "https://login.microsoftonline.example/authorize"

        _, kwargs = mock_build.call_args
        state = kwargs.get("state")
        assert state, f"build_auth_url no recibió state kwarg: {mock_build.call_args}"
        assert state != "helpdesk"  # ya no es el app_key predecible

        key = f"oauth:state:{state}"
        assert r.get(key) == "helpdesk"
        ttl = r.ttl(key)
        assert 0 < ttl <= get_settings().EMAIL_OAUTH_STATE_TTL
        r.delete(key)
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


def test_callback_rejects_unknown_state(app_client, auth_headers):
    with patch("itcj2.core.services.authz_cache.cached_roles",
               return_value={"admin"}), \
         patch("itcj2.core.utils.msgraph_mail.process_auth_code") as mock_process:
        resp = app_client.get(
            f"{CALLBACK_URL}?code=abc&state=no-such-nonce",
            headers=auth_headers, follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/config/email"
    mock_process.assert_not_called()


def test_callback_rejects_expired_state(app_client, auth_headers):
    r = get_redis()
    r.setex("oauth:state:expiring-nonce-f1a", 1, "helpdesk")
    time.sleep(1.2)  # dejar expirar el TTL
    with patch("itcj2.core.services.authz_cache.cached_roles",
               return_value={"admin"}), \
         patch("itcj2.core.utils.msgraph_mail.process_auth_code") as mock_process:
        resp = app_client.get(
            f"{CALLBACK_URL}?code=abc&state=expiring-nonce-f1a",
            headers=auth_headers, follow_redirects=False,
        )
    assert resp.status_code == 302
    mock_process.assert_not_called()


def test_callback_accepts_valid_state_and_consumes_it(app_client, auth_headers):
    r = get_redis()
    r.setex("oauth:state:valid-nonce-f1a", 600, "helpdesk")
    try:
        with patch("itcj2.core.services.authz_cache.cached_roles",
                   return_value={"admin"}), \
             patch("itcj2.core.utils.msgraph_mail.process_auth_code",
                   return_value={"name": "X", "username": "x@y"}) as mock_process:
            resp = app_client.get(
                f"{CALLBACK_URL}?code=abc&state=valid-nonce-f1a",
                headers=auth_headers, follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/itcj/config/email"
        mock_process.assert_called_once_with("helpdesk", "abc")
        assert r.get("oauth:state:valid-nonce-f1a") is None  # un solo uso
    finally:
        r.delete("oauth:state:valid-nonce-f1a")


def test_callback_requires_login(app_client):
    resp = app_client.get(f"{CALLBACK_URL}?code=abc&state=x", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/login"


def test_callback_requires_admin(app_client, student_headers):
    with patch("itcj2.core.services.authz_cache.cached_roles", return_value=set()), \
         patch("itcj2.core.services.authz_cache.cached_has_assignment",
               return_value=False):
        resp = app_client.get(
            f"{CALLBACK_URL}?code=abc&state=x",
            headers=student_headers, follow_redirects=False,
        )
    assert resp.status_code == 403
