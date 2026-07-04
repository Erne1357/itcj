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
    # se revisan (compat pre-9ee70d5). Fail-open si Redis/el servicio fallan:
    # una caída de Redis nunca tira los websockets de toda la plataforma.
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
