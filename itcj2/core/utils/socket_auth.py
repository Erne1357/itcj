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
    # Revocación de sesión (espejo de itcj2/middleware.py): si el token trae claim
    # `sv` y no coincide con la versión vigente, está revocado. Tokens viejos SIN
    # `sv` no se revisan (compat pre-9ee70d5). `current_version` devuelve None si no
    # pudo consultar el almacén: en ese caso NO se revoca (fail-open real).
    if "sv" in data:
        try:
            from itcj2.core.services.session_service import current_version
            cur = current_version(int(data["sub"]))
            if cur is not None and int(data.get("sv", 0)) != cur:
                return None
        except Exception:
            pass
    return {
        "sub": data.get("sub"),
        "role": data.get("role"),
        "cn": data.get("cn"),
        "name": data.get("name"),
    }
