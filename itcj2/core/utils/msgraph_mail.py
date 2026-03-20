# itcj/core/utils/msgraph_mail.py
"""
Utilidad centralizada de Microsoft Graph para envio de correo.

Cada app de ITCJ puede conectar su propia cuenta de correo.
Los tokens se almacenan por separado en instance/apps/{app_key}/email/.
Se usa un unico registro de app en Azure AD (credenciales compartidas).
"""
import json
import os
import threading
from pathlib import Path

import msal
import requests

TENANT_ID = os.getenv("MS_TENANT_ID", "")
CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_URI = os.getenv(
    "MS_REDIRECT_URI",
    "http://localhost:8080/itcj/config/email/auth/callback",
)

_SCOPES_RAW = (os.getenv("MS_SCOPES") or "Mail.Send").split()
_SCOPES_FULL = (
    os.getenv("MS_SCOPES") or "offline_access openid profile Mail.Send"
).split()
_RESERVED = {"openid", "profile", "offline_access"}

_INSTANCE_BASE = Path(
    os.getenv("MS_INSTANCE_BASE", "/app/instance/apps")
)
_LOCK = threading.Lock()


def _scopes_for_auth():
    return [s for s in _SCOPES_RAW if s and s not in _RESERVED]


def _email_dir(app_key: str) -> Path:
    return _INSTANCE_BASE / app_key / "email"


def _cache_path(app_key: str) -> Path:
    return _email_dir(app_key) / "msal_cache.json"


def _acct_path(app_key: str) -> Path:
    return _email_dir(app_key) / "msal_account.json"


def _ensure_dirs(app_key: str):
    _email_dir(app_key).mkdir(parents=True, exist_ok=True)


def load_cache(app_key: str) -> msal.SerializableTokenCache:
    _ensure_dirs(app_key)
    cache = msal.SerializableTokenCache()
    cp = _cache_path(app_key)
    if cp.exists():
        with _LOCK, open(cp, "r", encoding="utf-8") as f:
            cache.deserialize(f.read())
    return cache


def save_cache(app_key: str, cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        _ensure_dirs(app_key)
        with _LOCK, open(_cache_path(app_key), "w", encoding="utf-8") as f:
            f.write(cache.serialize())


def get_msal_app(app_key: str, cache=None) -> msal.ConfidentialClientApplication:
    cache = cache or load_cache(app_key)
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache,
    )


def save_account_info(app_key: str, account: dict):
    _ensure_dirs(app_key)
    with _LOCK, open(_acct_path(app_key), "w", encoding="utf-8") as f:
        json.dump(
            {
                "home_account_id": account.get("home_account_id"),
                "username": account.get("username"),
                "name": account.get("name"),
            },
            f,
        )


def read_account_info(app_key: str) -> dict | None:
    ap = _acct_path(app_key)
    if not ap.exists():
        return None
    with _LOCK, open(ap, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_account_and_cache(app_key: str):
    with _LOCK:
        cp = _cache_path(app_key)
        ap = _acct_path(app_key)
        if cp.exists():
            cp.unlink()
        if ap.exists():
            ap.unlink()


def build_auth_url(app_key: str) -> str:
    """Genera la URL de autorizacion de Microsoft. Usa app_key como state."""
    app = get_msal_app(app_key)
    return app.get_authorization_request_url(
        _scopes_for_auth(),
        redirect_uri=REDIRECT_URI,
        state=app_key,
        prompt="select_account",
    )


def process_auth_code(app_key: str, code: str) -> dict:
    """
    Intercambia el code por tokens y persiste cache + archivo de cuenta.
    Retorna dict con info basica de usuario (name, preferred_username).
    """
    cache = load_cache(app_key)
    app = get_msal_app(app_key, cache)
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=_scopes_for_auth(),
        redirect_uri=REDIRECT_URI,
    )
    if "access_token" not in result:
        return {
            "error": result.get("error"),
            "error_description": result.get("error_description"),
        }

    accounts = app.get_accounts()
    if accounts:
        save_account_info(
            app_key,
            {
                "home_account_id": accounts[0].get("home_account_id"),
                "username": accounts[0].get("username"),
                "name": result.get("id_token_claims", {}).get("name"),
            },
        )
    save_cache(app_key, cache)

    idc = result.get("id_token_claims", {})
    return {"name": idc.get("name"), "username": idc.get("preferred_username")}


def acquire_token_silent(app_key: str) -> str | None:
    """Intenta renovar un access token usando el refresh token del cache."""
    cache = load_cache(app_key)
    app = get_msal_app(app_key, cache)
    acct = read_account_info(app_key)
    if not acct:
        return None

    account = None
    for a in app.get_accounts():
        if a.get("home_account_id") == acct.get("home_account_id"):
            account = a
            break
    if not account:
        return None

    result = app.acquire_token_silent(_SCOPES_FULL, account=account)
    save_cache(app_key, cache)
    if not result or "access_token" not in result:
        return None
    return result["access_token"]


def graph_send_mail(
    access_token: str,
    subject: str,
    content_html: str,
    to_list: list[str],
    save_to_sent: bool = True,
):
    """Envio delegado: usa /me/sendMail (envia como el usuario autenticado)."""
    endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": content_html},
            "toRecipients": [
                {"emailAddress": {"address": a}} for a in to_list
            ],
        },
        "saveToSentItems": bool(save_to_sent),
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    return requests.post(endpoint, headers=headers, json=payload, timeout=30)
