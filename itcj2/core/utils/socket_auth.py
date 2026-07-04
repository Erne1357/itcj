from itcj2.core.utils.jwt_tools import decode_jwt


def current_user_from_environ(environ):
    """
    Extrae el usuario actual desde la cookie 'itcj_token' en el handshake WS.
    Devuelve un dict {sub, role, cn, name} o None si no hay cookie válida.
    """
    cookie_header = environ.get("HTTP_COOKIE", "") or ""
    token = None
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "itcj_token":
            token = v
            break
    if not token:
        return None
    data = decode_jwt(token)
    if not data:
        return None
    # Revocación de sesión (espejo de itcj2/middleware.py:60-69): si el token
    # trae claim `sv` y no coincide con la versión vigente del usuario, está
    # revocado (logout/desactivación/cambio de rol). Tokens viejos SIN `sv` no
    # se revisan (compat pre-9ee70d5). OJO: esto NO es fail-open ante una caída
    # real de Redis — session_service.current_version() atrapa la excepción y
    # devuelve 0, así que un token con `sv` != 0 (ya tuvo al menos un bump) deja
    # de matchear y se rechaza (fail-CLOSED). Solo sobreviven sin verse
    # afectados los tokens con sv==0 (nunca bumpeados). Es el mismo
    # comportamiento de middleware.py — herencia intencional, no un bug propio
    # de este módulo.
    if "sv" in data:
        try:
            from itcj2.core.services.session_service import current_version
            if int(data.get("sv", 0)) != current_version(int(data["sub"])):
                return None
        except Exception:
            pass
    return {
        "sub": data.get("sub"),
        "role": data.get("role"),
        "cn": data.get("cn"),
        "name": data.get("name"),
    }
