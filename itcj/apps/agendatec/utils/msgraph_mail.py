# utils/ms_graph.py
import os, json, threading
from pathlib import Path
import msal, requests
from flask import current_app

TENANT_ID     = os.getenv("MS_TENANT_ID", "")
CLIENT_ID     = os.getenv("MS_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
AUTHORITY     = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES        = (os.getenv("MS_SCOPES") or "offline_access openid profile Mail.Send").split()
REDIRECT_URI  = os.getenv("MS_REDIRECT_URI", "http://localhost:8080/agendatec/surveys/auth/callback")

_SCOPES_RAW = (os.getenv("MS_SCOPES") or "Mail.send").split()
_RESERVED = {"openid","profile","offline_access"}

CACHE_PATH    = os.getenv("MS_CACHE_PATH", "instance/apps/agendatec/email/msal_cache.json")
ACCT_PATH     = os.getenv("MS_ACCOUNT_PATH", "instance/apps/agendatec/email/msal_account.json")  # quién inició sesión
LOCK = threading.Lock()

def _scopes_for_auth():
    # MSAL ya añade los reservados; no los incluyas o lanzará ValueError
    return [s for s in _SCOPES_RAW if s and s not in _RESERVED]

def _ensure_dirs():
    Path(CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(ACCT_PATH).parent.mkdir(parents=True, exist_ok=True)

def load_cache() -> msal.SerializableTokenCache:
    _ensure_dirs()
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_PATH):
        with LOCK, open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache.deserialize(f.read())
    return cache

def save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with LOCK, open(CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(cache.serialize())

def get_msal_app(cache=None) -> msal.ConfidentialClientApplication:
    cache = cache or load_cache()
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )

def save_account_info(account: dict):
    _ensure_dirs()
    with LOCK, open(ACCT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "home_account_id": account.get("home_account_id"),
            "username": account.get("username"),
            "name": account.get("name")
        }, f)

def read_account_info() -> dict | None:
    if not os.path.exists(ACCT_PATH):
        return None
    with LOCK, open(ACCT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def clear_account_and_cache():
    with LOCK:
        if os.path.exists(CACHE_PATH): os.remove(CACHE_PATH)
        if os.path.exists(ACCT_PATH): os.remove(ACCT_PATH)

def build_auth_url(state: str):
    app = get_msal_app()
    return app.get_authorization_request_url(
        _scopes_for_auth(),
        redirect_uri=REDIRECT_URI,
        state=state,
        prompt="select_account",
    )

def process_auth_code(code: str) -> dict:
    """
    Intercambia el code por tokens y persiste en cache + archivo de cuenta.
    Retorna dict con info básica de usuario (name, preferred_username).
    """
    cache = load_cache()
    app = get_msal_app(cache)
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=_scopes_for_auth(),   # 👈 usa los mismos (sin reservados)
        redirect_uri=REDIRECT_URI
    )
    if "access_token" not in result:
        return {"error": result.get("error"), "error_description": result.get("error_description")}

    # Selecciona la cuenta (normalmente habrá una sola)
    accounts = app.get_accounts()
    if accounts:
        save_account_info({
            "home_account_id": accounts[0].get("home_account_id"),
            "username": accounts[0].get("username"),
            "name": result.get("id_token_claims", {}).get("name")
        })
    save_cache(cache)

    idc = result.get("id_token_claims", {})
    return {"name": idc.get("name"), "username": idc.get("preferred_username")}

def acquire_token_silent() -> str | None:
    """
    Intenta renovar un access token usando el refresh token del cache.
    """
    cache = load_cache()
    app = get_msal_app(cache)
    acct = read_account_info()
    if not acct:
        return None
    # Busca la cuenta en el cache por home_account_id
    account = None
    for a in app.get_accounts():
        if a.get("home_account_id") == acct.get("home_account_id"):
            account = a; break
    if not account:
        return None

    result = app.acquire_token_silent(SCOPES, account=account)
    save_cache(cache)
    if not result or "access_token" not in result:
        return None
    return result["access_token"]

def graph_send_mail(access_token: str, subject: str, content_html: str, to_list: list[str], save_to_sent=True):
    """
    Envío delegado: usa /me/sendMail (envía como el usuario que inició sesión).
    """
    endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": { "contentType": "HTML", "content": content_html },
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_list]
        },
        "saveToSentItems": bool(save_to_sent)
    }
    headers = { "Authorization": f"Bearer {access_token}", "Content-Type": "application/json" }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    return resp
