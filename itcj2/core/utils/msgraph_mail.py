# itcj/core/utils/msgraph_mail.py
"""
Utilidad centralizada de Microsoft Graph para envio de correo.

Cada app de ITCJ puede conectar su propia cuenta de correo.
Los tokens se almacenan por separado en instance/apps/{app_key}/email/.
Se usa un unico registro de app en Azure AD (credenciales compartidas).
"""
import json
import logging
import os
import re
import threading
from pathlib import Path

import msal
import requests

logger = logging.getLogger(__name__)

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

# app_key se usa como componente de ruta bajo instance/apps/. Antes se aceptaba
# cualquier string: el callback OAuth (sin auth previo a 09d8c58) pasaba el query
# param `state` crudo hasta mkdir(parents=True), y un escaneo automatizado creo
# ~80 directorios con nombres de payload bajo instance/apps/. La validacion vive
# aqui, no solo en el endpoint, para que ningun caller futuro pueda saltarsela.
_APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class InvalidAppKey(ValueError):
    """app_key que no puede usarse como componente de ruta."""


def _safe_app_key(app_key) -> str:
    if not isinstance(app_key, str) or not _APP_KEY_RE.fullmatch(app_key):
        raise InvalidAppKey(f"app_key invalido: {app_key!r}")
    return app_key


def _scopes_for_auth():
    return [s for s in _SCOPES_RAW if s and s not in _RESERVED]


def _email_dir(app_key: str) -> Path:
    """Directorio de tokens de una app. Lanza InvalidAppKey si el key no es seguro.

    Doble candado: allowlist por regex + verificacion de que la ruta resuelta
    sigue colgando de _INSTANCE_BASE (por si el regex se relajara despues).
    """
    d = _INSTANCE_BASE / _safe_app_key(app_key) / "email"
    if _INSTANCE_BASE.resolve() not in d.resolve().parents:
        raise InvalidAppKey(f"app_key escapa de la base: {app_key!r}")
    return d


def _cache_path(app_key: str) -> Path:
    return _email_dir(app_key) / "msal_cache.json"


def _acct_path(app_key: str) -> Path:
    return _email_dir(app_key) / "msal_account.json"


def _ensure_dirs(app_key: str):
    _email_dir(app_key).mkdir(parents=True, exist_ok=True)


def load_cache(app_key: str) -> msal.SerializableTokenCache:
    # Sin _ensure_dirs: leer NO debe crear directorios. Solo save_cache /
    # save_account_info crean, y solo despues de que app_key paso la validacion.
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
    # Fail-soft: la pagina de correo itera TODAS las apps de core_apps; un key raro
    # en BD no debe tumbar la pagina entera. Las escrituras si lanzan.
    try:
        ap = _acct_path(app_key)
    except InvalidAppKey:
        logger.warning("read_account_info con app_key invalido: %r", app_key)
        return None
    if not ap.exists():
        return None
    with _LOCK, open(ap, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_account_and_cache(app_key: str):
    try:
        cp = _cache_path(app_key)
        ap = _acct_path(app_key)
    except InvalidAppKey:
        logger.warning("clear_account_and_cache con app_key invalido: %r", app_key)
        return
    with _LOCK:
        if cp.exists():
            cp.unlink()
        if ap.exists():
            ap.unlink()


def build_auth_url(app_key: str, state: str | None = None) -> str:
    """Genera la URL de autorizacion de Microsoft.

    ``state`` debe ser el nonce anti-CSRF generado en email_auth_login
    (persistido en Redis como oauth:state:{nonce} -> app_key, C6). Fallback
    legacy ``state=app_key`` solo por retro-compatibilidad de firma.
    """
    _safe_app_key(app_key)
    app = get_msal_app(app_key)
    return app.get_authorization_request_url(
        _scopes_for_auth(),
        redirect_uri=REDIRECT_URI,
        state=state or app_key,
        prompt="select_account",
    )


def process_auth_code(app_key: str, code: str) -> dict:
    """
    Intercambia el code por tokens y persiste cache + archivo de cuenta.
    Retorna dict con info basica de usuario (name, preferred_username).

    Lanza InvalidAppKey si app_key no es usable como componente de ruta: esta es
    la ruta que el escaneo abuso, asi que aqui se falla duro, no en silencio.
    """
    _safe_app_key(app_key)
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
    try:
        _safe_app_key(app_key)
    except InvalidAppKey:
        logger.warning("acquire_token_silent con app_key invalido: %r", app_key)
        return None
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
